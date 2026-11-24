#!/usr/bin/python3
"""Install/remove the quick installer's IPv4 rules on its one LAN interface."""
import json
from pathlib import Path
import subprocess
import sys

NETWORK = Path('/opt/home-vpn-gateway/network.json')
STATE = Path('/run/home-vpn-lan-state.json')
PRIVATE = ('0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
           '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4', '240.0.0.0/4')
GAME_SERVERS = ('51.254.107.154', '51.210.222.226', '158.69.120.230', '139.99.90.70')
TABLE = '100'
PRIORITY = '11000'
RULE = ['priority', PRIORITY, 'fwmark', '1/1', 'lookup', TABLE]
ROUTE = ['local', 'default', 'dev', 'lo', 'table', TABLE]


def output(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)


def iptables(table, *args, check=True):
    return output('iptables', '-w', '5', '-t', table, *args, check=check)


def rules(net):
    incoming = ['-i', net['iface'], '-s', net['cidr']]
    outgoing = ['-o', net['iface']]
    tcp = []
    for protocol in ('udp', 'tcp'):
        tcp.append(['-p', protocol, '--dport', '53', '-j', 'REDIRECT', '--to-ports', '53'])
    tcp.append(['-m', 'addrtype', '--dst-type', 'LOCAL', '-j', 'RETURN'])
    tcp.extend(['-d', dst, '-j', 'RETURN'] for dst in (*PRIVATE, net['vps']))
    tcp.append(['-p', 'tcp', '-j', 'REDIRECT', '--to-ports', '12345'])

    chains = {
        ('nat', 'HVG_PRE'): tcp,
        ('filter', 'HVG_FORWARD'): [
            ['-p', 'udp', '--dport', '443', '-j', 'REJECT', '--reject-with', 'icmp-port-unreachable'],
            ['-j', 'ACCEPT'],
        ],
        ('mangle', 'XRAY_UDP'): [
            ['-p', 'udp', '--dport', '53', '-j', 'RETURN'],
            ['-p', 'udp', '--dport', '19300:19309', '-j', 'RETURN'],
            ['-p', 'udp', '-j', 'TPROXY', '--on-port', '12346', '--on-ip', '127.0.0.1',
             '--tproxy-mark', '0x1/0x1'],
        ],
    }
    own = ['-m', 'comment', '--comment', 'home-vpn-gateway']
    hooks = [
        ('nat', 'PREROUTING', incoming + own + ['-j', 'HVG_PRE']),
        ('nat', 'POSTROUTING', outgoing + ['-s', net['cidr']] + own + ['-j', 'MASQUERADE']),
        ('filter', 'FORWARD', incoming + outgoing + own + ['-j', 'HVG_FORWARD']),
        ('filter', 'FORWARD', ['-i', net['iface'], '-d', net['cidr']] + outgoing +
         ['-m', 'conntrack', '--ctstate', 'RELATED,ESTABLISHED'] + own + ['-j', 'ACCEPT']),
    ]
    hooks.extend(('mangle', 'PREROUTING', incoming + ['-d', dst, '-p', 'udp'] + own + ['-j', 'XRAY_UDP'])
                 for dst in GAME_SERVERS)
    return chains, hooks


def check_available(net):
    chains, _ = rules(net)
    for table, chain in chains:
        if iptables(table, '-S', chain, check=False).returncode == 0:
            raise ValueError(f'Цепочка {chain} уже используется.')
    # A missing table returns exit code 2 on Debian.
    table = output('ip', '-4', 'route', 'show', 'table', TABLE, check=False)
    if table.stdout.strip() or table.returncode not in (0, 2):
        raise ValueError(f'Таблица маршрутизации {TABLE} занята или недоступна.')
    for rule in json.loads(output('ip', '-j', '-4', 'rule').stdout):
        if (str(rule.get('table')) == TABLE or str(rule.get('priority')) == PRIORITY
                or 'fwmark' in rule):
            raise ValueError('На сервере уже есть правило policy routing с таблицей 100, меткой или приоритетом 11000.')


def sysctls(net):
    base = Path('/proc/sys/net/ipv4')
    return {base / 'ip_forward': '1', base / 'conf/all/send_redirects': '0',
            base / 'conf' / net['iface'] / 'send_redirects': '0'}


def down():
    if not STATE.exists():
        return
    saved = json.loads(STATE.read_text())
    chains, hooks = rules(saved['network'])
    for table, parent, args in reversed(hooks):
        if iptables(table, '-C', parent, *args, check=False).returncode == 0:
            iptables(table, '-D', parent, *args)
    for table, chain in chains:
        if iptables(table, '-S', chain, check=False).returncode == 0:
            iptables(table, '-F', chain)
            iptables(table, '-X', chain)
    output('ip', '-4', 'rule', 'del', *RULE, check=False)
    output('ip', '-4', 'route', 'del', *ROUTE, check=False)
    for name, value in saved['sysctls'].items():
        path = Path(name)
        if path.exists() and path.read_text().strip() != value:
            path.write_text(value + '\n')
    STATE.unlink()


def up(net):
    down()
    check_available(net)
    settings = sysctls(net)
    before = {str(p): p.read_text().strip() for p in settings}
    STATE.write_text(json.dumps({'network': net, 'sysctls': before}))
    try:
        for path, value in settings.items():
            if path.read_text().strip() != value:
                path.write_text(value + '\n')
        output('ip', '-4', 'route', 'add', *ROUTE)
        output('ip', '-4', 'rule', 'add', *RULE)
        chains, hooks = rules(net)
        for (table, chain), entries in chains.items():
            iptables(table, '-N', chain)
            for entry in entries:
                iptables(table, '-A', chain, *entry)
        for table, parent, args in hooks:
            iptables(table, '-I', parent, '1', *args)
    except BaseException:
        down()
        raise


if __name__ == '__main__':
    try:
        action, = sys.argv[1:]
        if action == 'down':
            down()
        elif action in ('up', 'check'):
            (up if action == 'up' else check_available)(json.loads(NETWORK.read_text()))
        else:
            sys.exit('Use check, up or down')
    except subprocess.CalledProcessError as error:
        sys.exit(f'{error.cmd}: {error.stderr.strip()}')
