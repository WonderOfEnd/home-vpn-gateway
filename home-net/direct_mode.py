#!/usr/bin/python3
"""Manage only HG_DIRECT_* chains for an IPv4 emergency gateway mode."""
import ipaddress
import os
import re
import subprocess
import sys

IPTABLES = '/usr/sbin/iptables'
IFACE = os.environ.get('HOME_GATEWAY_LAN_IFACE', 'enp2s0')
LAN = str(ipaddress.IPv4Network(os.environ.get('HOME_GATEWAY_LAN_CIDR', '192.168.0.0/24')))
DNS = str(ipaddress.IPv4Address(os.environ.get('HOME_GATEWAY_DIRECT_DNS', '1.1.1.1')))
if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,15}', IFACE):
    raise SystemExit('Invalid LAN interface')
if not ipaddress.IPv4Address(DNS).is_global or ipaddress.IPv4Address(DNS).is_multicast or ipaddress.IPv4Address(DNS).is_reserved:
    raise SystemExit('Emergency DNS must be a public IPv4 address')

CHAINS = [('nat', 'HG_DIRECT_PRE'), ('nat', 'HG_DIRECT_OUT'),
          ('nat', 'HG_DIRECT_POST'), ('mangle', 'HG_DIRECT_MANGLE'),
          ('filter', 'HG_DIRECT_FORWARD')]
HOOKS = [
    ('nat', 'PREROUTING', ['-i', IFACE, '-s', LAN, '-j', 'HG_DIRECT_PRE']),
    ('nat', 'OUTPUT', ['-j', 'HG_DIRECT_OUT']),
    ('nat', 'POSTROUTING', ['-o', IFACE, '-d', DNS, '-j', 'HG_DIRECT_POST']),
    ('mangle', 'PREROUTING', ['-i', IFACE, '-s', LAN, '-j', 'HG_DIRECT_MANGLE']),
    ('filter', 'FORWARD', ['-i', IFACE, '-o', IFACE, '-s', LAN, '-j', 'HG_DIRECT_FORWARD']),
]
PRIVATE = ['0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
           '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4', '240.0.0.0/4']


def ipt(table, *args, check=True):
    return subprocess.run([IPTABLES, '-w', '5', '-t', table, *args],
                          check=check, stdout=subprocess.DEVNULL,
                          stderr=None if check else subprocess.DEVNULL)


def remove():
    for table, parent, rule in reversed(HOOKS):
        while ipt(table, '-C', parent, *rule, check=False).returncode == 0:
            ipt(table, '-D', parent, *rule)
    for table, chain in reversed(CHAINS):
        if ipt(table, '-S', chain, check=False).returncode == 0:
            ipt(table, '-F', chain)
            ipt(table, '-X', chain)


def install():
    if not os.path.isdir('/sys/class/net/' + IFACE):
        raise SystemExit('LAN interface does not exist: ' + IFACE)
    remove()
    try:
        for table, chain in CHAINS:
            ipt(table, '-N', chain)
        for protocol in ['udp', 'tcp']:
            ipt('nat', '-A', 'HG_DIRECT_PRE', '-p', protocol, '--dport', '53',
                '-j', 'DNAT', '--to-destination', DNS + ':53')
            ipt('nat', '-A', 'HG_DIRECT_OUT', '-p', protocol, '-m', 'multiport',
                '--dports', '53,5353', '-m', 'addrtype', '--dst-type', 'LOCAL',
                '-j', 'DNAT', '--to-destination', DNS + ':53')
            for source in [LAN, '127.0.0.0/8']:
                ipt('nat', '-A', 'HG_DIRECT_POST', '-s', source, '-p', protocol,
                    '--dport', '53', '-j', 'MASQUERADE')
        # Keep access to local services, Docker published ports and private networks.
        for table, chain in [('nat', 'HG_DIRECT_PRE'), ('mangle', 'HG_DIRECT_MANGLE')]:
            ipt(table, '-A', chain, '-m', 'addrtype', '--dst-type', 'LOCAL', '-j', 'RETURN')
            for network in PRIVATE:
                ipt(table, '-A', chain, '-d', network, '-j', 'RETURN')
            ipt(table, '-A', chain, '-j', 'ACCEPT')
        ipt('filter', '-A', 'HG_DIRECT_FORWARD', '-j', 'ACCEPT')
        for table, parent, rule in HOOKS:
            ipt(table, '-I', parent, '1', *rule)
    except Exception:
        remove()
        raise


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Run through home-gateway-direct.service')
    if len(sys.argv) != 2 or sys.argv[1] not in ('on', 'off'):
        raise SystemExit('Expected on or off')
    (install if sys.argv[1] == 'on' else remove)()
