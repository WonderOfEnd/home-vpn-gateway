#!/usr/bin/env python3
"""Interactive installation on a fresh, single-interface Debian 13 home server."""
import argparse
import base64
import binascii
import fcntl
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
import uuid
import zipfile

REPO = Path(__file__).resolve().parent
BASE = Path('/opt/home-vpn-gateway')
PRIVATE = BASE / 'private'
STATE = PRIVATE / 'install.json'
UNIT_DIR = Path('etc/systemd/system')
XRAY_VERSION = 'v26.11.9'
XRAY_ARCHIVES = {
    'x86_64': ('64', 'b651f7e1d9966ee2c1b1ee1bf8b52c72771824d3065dce96bbc8bcc19ed95f82'),
    'aarch64': ('arm64-v8a', '64ed6858982a7f5eb85d88b811089063bd4f17561f4c8f44e0f1dc8e6f6430be'),
}
PIHOLE_IMAGE = ('pihole/pihole:2026.11.0@sha256:'
                '66c798d79a95c2691f280329c3611dba1746117c61c9f331907ca35a06a52778')
DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']
COMPOSE = [*DOCKER, 'compose', '--project-name', 'home-vpn-gateway', '--env-file',
           str(PRIVATE / '.env'), '-f', str(PRIVATE / 'compose.json')]
PACKAGES = ['ca-certificates', 'curl', 'sudo', 'iptables', 'iproute2',
            'docker.io', 'docker-cli', 'docker-compose', 'bind9-dnsutils']
LAN_RANGES = tuple(map(ipaddress.IPv4Network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')))


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def capture(*args):
    return subprocess.check_output(args, text=True).strip()


def compose(*args):
    # Compose gives shell variables precedence over the private .env file.
    env = dict(os.environ)
    env.pop('PIHOLE_PASSWORD', None)
    run(*COMPOSE, *args, env=env)


def save_json(path, value, mode=0o600):
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.chmod(mode)
    temporary.replace(path)


def hostname(value):
    labels = value.split('.')
    return (1 < len(labels) and len(value) <= 253 and
            all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in labels))


def parse_link(link):
    try:
        url = urlsplit(link.strip())
        port = url.port
        client_id = str(uuid.UUID(url.username or ''))
        if url.scheme != 'vless' or url.password is not None or url.path not in ('', '/') or not port:
            raise ValueError
        query = parse_qs(url.query, keep_blank_values=True, max_num_fields=40)
        if any(len(values) != 1 for values in query.values()):
            raise ValueError
    except ValueError:
        raise ValueError('Нужна целая клиентская ссылка vless:// с UUID, адресом и портом.') from None
    opts = {key: values[0] for key, values in query.items()}
    if (opts.get('security') != 'reality' or opts.get('type', 'tcp') not in ('tcp', 'raw')
            or opts.get('encryption', 'none') != 'none' or opts.get('headerType', 'none') != 'none'
            or opts.get('flow', '') not in ('', 'xtls-rprx-vision')):
        raise ValueError('Поддерживается VLESS, RAW/TCP, REALITY, encryption=none, с Vision или без flow.')
    accepted = {'security', 'type', 'encryption', 'headerType', 'flow', 'pbk', 'sid', 'sni', 'fp', 'spx', 'pqv'}
    # 3X-UI includes this client capability hint on ordinary REALITY share links.
    if opts.get('support-x25519mlkem768') == 'true':
        accepted.add('support-x25519mlkem768')
    if any(value and key not in accepted for key, value in opts.items()):
        raise ValueError('В ссылке есть дополнительные параметры транспорта. Создайте обычный профиль TCP + REALITY.')
    key = opts.get('pbk', '')
    try:
        if (not re.fullmatch(r'[A-Za-z0-9_-]{43}', key) or
                len(base64.b64decode(key + '=', altchars=b'-_', validate=True)) != 32):
            raise ValueError
    except (ValueError, binascii.Error):
        raise ValueError('Проверьте Public key (pbk) в ссылке REALITY.') from None
    if not hostname(opts.get('sni', '')) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}){0,8}', opts.get('sid', '')):
        raise ValueError('Проверьте Server Name (SNI) и Short ID в настройках REALITY.')
    endpoint = url.hostname or ''
    try:
        address = ipaddress.IPv4Address(endpoint)
    except ValueError:
        if not hostname(endpoint):
            raise ValueError('В адресе профиля нужен публичный IPv4 VPS или домен с A-записью.') from None
        try:
            found = {item[4][0] for item in socket.getaddrinfo(endpoint, port, socket.AF_INET, socket.SOCK_STREAM)}
        except OSError:
            raise ValueError('Не удалось получить IPv4 по имени VPS. Проверьте DNS или укажите IP в профиле.') from None
        if len(found) != 1:
            raise ValueError('У домена несколько адресов. Укажите в профиле постоянный IPv4 своего VPS.')
        address = ipaddress.IPv4Address(found.pop())
    if not address.is_global or address.is_multicast or address.is_reserved:
        raise ValueError('В адресе профиля нужен публичный IPv4 вашего VPS.')
    reality = {'serverName': opts['sni'], 'publicKey': key, 'shortId': opts.get('sid', ''),
               'fingerprint': opts.get('fp') or 'chrome', 'spiderX': opts.get('spx') or '/'}
    if opts.get('pqv'):
        reality['mldsa65Verify'] = opts['pqv']
    return {'vps': str(address), 'port': port, 'uuid': client_id, 'reality': reality, 'flow': opts.get('flow', '')}


def network():
    routes = json.loads(capture('ip', '-j', '-4', 'route', 'show', 'default'))
    if len(routes) != 1 or not routes[0].get('gateway'):
        raise ValueError('Нужен один IPv4-маршрут по умолчанию через домашний роутер.')
    iface = routes[0]['dev']
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', iface):
        raise ValueError('Не удалось определить имя LAN-интерфейса.')
    router = ipaddress.IPv4Address(routes[0]['gateway'])
    addresses = json.loads(capture('ip', '-j', '-4', 'addr', 'show', 'dev', iface))[0]['addr_info']
    nets = [ipaddress.IPv4Interface(f"{a['local']}/{a['prefixlen']}") for a in addresses if a['scope'] == 'global']
    if (len(nets) != 1 or router not in nets[0].network or router == nets[0].ip or
            not any(nets[0].network.subnet_of(private) for private in LAN_RANGES)):
        raise ValueError('Запустите мастер на домашнем сервере с одним частным IPv4 в сети роутера.')
    return {'iface': iface, 'ip': str(nets[0].ip), 'cidr': str(nets[0].network), 'router': str(router)}


def xray_config(profile, lan_ip):
    config = json.loads((REPO / 'xray/config.json').read_text())
    config['log']['error'] = ''  # systemd journal
    for inbound in config['inbounds']:
        if inbound['tag'] == 'redirect-in':
            inbound['listen'] = lan_ip  # PREROUTING REDIRECT selects the LAN address.
        if inbound['tag'] == 'tproxy-udp-in':
            inbound['listen'] = '127.0.0.1'  # Matches the TPROXY --on-ip rule.
    for outbound in config['outbounds']:
        if outbound['protocol'] != 'vless':
            continue
        server, = outbound['settings']['vnext']
        user, = server['users']
        user['id'] = profile['uuid']
        if profile['flow']:
            user['flow'] = profile['flow']
            outbound.pop('mux', None)  # Vision handles its connections without Mux.
        server.update(address=profile['vps'], port=profile['port'])
        outbound['streamSettings']['realitySettings'] = dict(profile['reality'])
    return config


def compose_config(net):
    config = json.loads((REPO / 'pihole/docker-compose.json').read_text())
    service = config['services']['pihole']
    service['image'] = PIHOLE_IMAGE
    service.pop('cap_add', None)  # The router provides DHCP.
    service['environment'].update(FTLCONF_dns_interface=net['iface'], FTLCONF_dns_listeningMode='BIND',
                                  FTLCONF_dns_upstreams='127.0.0.1#5353',
                                  FTLCONF_webserver_port=net['ip'] + ':8080', TZ='Etc/UTC')
    return config


def stage_files(stage, net, profile):
    run('bash', REPO / 'home-net/install.sh', '--stage', stage)
    units = stage / UNIT_DIR
    shutil.copyfile(REPO / 'systemd/xray.service', units / 'xray.service')
    shutil.copyfile(REPO / 'setup/home-vpn-lan.service', units / 'home-vpn-lan.service')
    (units / 'xray.service.d').mkdir()
    shutil.copyfile(REPO / 'setup/xray-credentials.conf', units / 'xray.service.d/20-gateway.conf')
    direct = units / 'home-gateway-direct.service.d'
    direct.mkdir()
    (direct / '20-gateway.conf').write_text('[Unit]\nAfter=home-vpn-lan.service\nPartOf=home-vpn-lan.service\n')
    config = stage / 'usr/local/etc/xray/config.json'
    config.parent.mkdir(parents=True)
    save_json(config, xray_config(profile, net['ip']))
    (stage / 'etc/default/home-gateway-direct').write_text(
        f"HOME_GATEWAY_LAN_IFACE={net['iface']}\nHOME_GATEWAY_LAN_CIDR={net['cidr']}\nHOME_GATEWAY_DIRECT_DNS=1.1.1.1\n")


def fresh_host(stage, net):
    for item in stage.rglob('*'):
        if item.is_file() and os.path.lexists(Path('/') / item.relative_to(stage)):
            raise ValueError(f'Уже существует /{item.relative_to(stage)}. Мастер предназначен для новой установки.')
    for unit in ('xray.service', 'home-vpn-lan.service', 'home-gateway-direct.service'):
        if capture('systemctl', 'show', '-p', 'LoadState', '--value', unit) != 'not-found':
            raise ValueError(f'Служба {unit} уже существует. Выберите чистую систему.')
    for unit in ('ufw', 'firewalld', 'netfilter-persistent', 'nftables'):
        if (subprocess.run(['systemctl', 'is-active', '--quiet', unit]).returncode == 0 or
                subprocess.run(['systemctl', 'is-enabled', '--quiet', unit],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0):
            raise ValueError(f'Включена служба {unit}. Для мастера нужен отдельный чистый Debian.')
    # Protect an existing host even if its Docker socket is currently stopped.
    if Path('/var/lib/docker/containers').is_dir() and any(Path('/var/lib/docker/containers').iterdir()):
        raise ValueError('Обнаружены контейнеры Docker. Выберите отдельную машину или ВМ.')
    ports = {'127.0.0.1': [(53, 'tcp'), (53, 'udp'), (5353, 'udp'), (10808, 'tcp'), (12346, 'udp')],
             net['ip']: [(53, 'tcp'), (53, 'udp'), (8080, 'tcp'), (12345, 'tcp')]}
    for address, bindings in ports.items():
        for port, proto in bindings:
            typ = socket.SOCK_STREAM if proto == 'tcp' else socket.SOCK_DGRAM
            with socket.socket(socket.AF_INET, typ) as sock:
                try:
                    sock.bind((address, port))
                except OSError:
                    raise ValueError(f'Недоступен {address}:{port}/{proto}. Проверьте занятые порты командой sudo ss -lntup.') from None


def install_xray():
    arch, checksum = XRAY_ARCHIVES[platform.machine()]
    url = f'https://github.com/XTLS/Xray-core/releases/download/{XRAY_VERSION}/Xray-linux-{arch}.zip'
    dest = BASE / 'xray'
    dest.mkdir(mode=0o755)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp, 'xray.zip')
        run('curl', '--fail', '--silent', '--show-error', '--location', '--retry', '2',
            '--proto', '=https', '--max-time', '300', '-o', archive, url)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
            raise ValueError('Контрольная сумма архива Xray не совпала.')
        with zipfile.ZipFile(archive) as release:
            for name in ('xray', 'geoip.dat', 'geosite.dat'):
                with release.open(name) as source, (dest / name).open('xb') as target:
                    shutil.copyfileobj(source, target)
                (dest / name).chmod(0o755 if name == 'xray' else 0o644)


def install(stage, net):
    BASE.mkdir(mode=0o755)
    PRIVATE.mkdir(mode=0o700)
    state = {'files': [], 'compose_started': False, 'complete': False}
    save_json(STATE, state)
    shutil.copyfile(__file__, BASE / 'install.py')
    shutil.copyfile(REPO / 'setup/routes.py', BASE / 'routes.py')
    save_json(BASE / 'network.json', net, 0o644)
    print('Устанавливаю пакеты Debian и проверяю архив Xray.', flush=True)
    env = dict(os.environ, DEBIAN_FRONTEND='noninteractive')
    run('apt-get', 'update', env=env)
    run('apt-get', '-y', '--no-install-recommends', '--no-remove', 'install', *PACKAGES, env=env)
    run('systemctl', 'enable', '--now', 'docker.service')
    if capture(*DOCKER, 'ps', '-aq'):
        raise ValueError('Обнаружены существующие контейнеры. Для новой установки нужна отдельная машина.')
    run('python3', BASE / 'routes.py', 'check')
    install_xray()
    run(BASE / 'xray/xray', 'run', '-test', '-config', stage / 'usr/local/etc/xray/config.json',
        env=dict(os.environ, XRAY_LOCATION_ASSET=str(BASE / 'xray')))
    passwd = PRIVATE / '.env'
    passwd.write_text('PIHOLE_PASSWORD=' + secrets.token_urlsafe(24) + '\n')
    passwd.chmod(0o600)
    save_json(PRIVATE / 'compose.json', compose_config(net))
    compose('config', '--quiet')
    compose('pull')
    for source in sorted(stage.rglob('*')):
        if not source.is_file():
            continue
        target = Path('/') / source.relative_to(stage)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create. Never replace an existing file, even on a retry.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, source.stat().st_mode & 0o777)
        with os.fdopen(fd, 'wb') as stream, source.open('rb') as original:
            state['files'].append(str(target))
            save_json(STATE, state)
            shutil.copyfileobj(original, stream)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'xray.service')
    state['compose_started'] = True
    save_json(STATE, state)
    compose('up', '-d')
    print('Проверяю HTTPS через VPN и ответ DNS от Pi-hole…', flush=True)
    for _ in range(12):
        if subprocess.run(['/usr/local/bin/home-net', 'status'], stdout=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(2)
    else:
        raise ValueError('Туннель или DNS не отвечает. Проверьте профиль на телефоне, порт VPS и доступ к DNS с VPS.')
    run('systemctl', 'enable', '--now', 'home-vpn-lan.service')
    run('systemctl', 'is-active', '--quiet', 'home-vpn-lan.service')
    run('/usr/local/bin/home-net', 'status')
    state['complete'] = True
    save_json(STATE, state)


def uninstall():
    state = json.loads(STATE.read_text())
    units = {Path(f).name for f in state['files']
             if Path(f).parent == Path('/') / UNIT_DIR and Path(f).is_file()}
    if units:
        run('systemctl', 'daemon-reload')
    for unit in ('home-net-notify.timer', 'home-net-watchdog.timer', 'home-net-notify.service',
                 'home-net-watchdog.service', 'home-gateway-direct.service', 'home-vpn-lan.service', 'xray.service'):
        if unit in units:
            run('systemctl', 'stop', unit)
            if unit not in ('home-net-notify.service', 'home-net-watchdog.service'):
                run('systemctl', 'disable', unit)
    if 'home-vpn-lan.service' in units:
        run('python3', BASE / 'routes.py', 'down')
    if state['compose_started']:
        compose('down')
        state['compose_started'] = False
        save_json(STATE, state)
    # Retain installed files (including any subsequent edits) alongside Pi-hole data.
    for name in reversed(state['files']):
        path = Path(name)
        if os.path.lexists(path):
            saved = PRIVATE / 'removed' / path.relative_to('/')
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(saved))
    if units:
        run('systemctl', 'daemon-reload')
    archive = BASE.with_name(BASE.name + '.backup-' + str(time.time_ns()))
    BASE.chmod(0o700)
    BASE.rename(archive)
    print(f'Файлы шлюза и данные Pi-hole сохранены в {archive}. Установленные пакеты Debian остаются в системе.')


def main():
    parser = argparse.ArgumentParser(description='Мастер домашнего VPN-шлюза для чистого Debian 13')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--plan', action='store_true', help='проверить ссылку и показать план без установки')
    modes.add_argument('--uninstall', action='store_true', help='отключить шлюз и сохранить его данные в архивном каталоге')
    args = parser.parse_args()
    if not args.plan and os.geteuid() != 0:
        raise ValueError('Запустите мастер через sudo.')
    if not args.plan:
        os.umask(0o022)  # Public program directories; credentials have their own 0600/0700 modes.
        lock = open('/run/lock/home-vpn-install.lock', 'a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Другой экземпляр мастера ещё работает.') from None
    if args.uninstall:
        if not STATE.is_file():
            print('Установка этого мастера не найдена.')
        elif input('Сначала верните прежний шлюз и DNS на устройствах/роутере. Отключить шлюз? [да/Нет] ').strip().lower() == 'да':
            uninstall()
        return
    if BASE.exists():
        if STATE.is_file() and json.loads(STATE.read_text()).get('complete'):
            print('Шлюз уже установлен. Проверка: home-net status')
            return
        raise ValueError(f'Каталог {BASE} уже занят. Для прерванной установки запустите мастер с --uninstall.')
    system = platform.freedesktop_os_release()
    if system.get('ID') != 'debian' or system.get('VERSION_ID') != '13' or platform.machine() not in XRAY_ARCHIVES:
        raise ValueError('Нужен Debian 13 (amd64 или arm64) на домашнем сервере или в ВМ.')
    if not Path('/run/systemd/system').is_dir():
        raise ValueError('Нужен сервер с загруженным systemd.')
    net = network()
    print(f"Домашний сервер {net['ip']} · {net['iface']} · сеть {net['cidr']} · роутер {net['router']}")
    if not sys.stdin.isatty():
        raise ValueError('Для скрытого ввода ссылки нужен терминал. При подключении по SSH используйте ssh -t.')
    while True:
        link = getpass.getpass('Вставьте ссылку vless://. Enter без ссылки — выход (ввод скрыт): ')
        if not link.strip():
            print('Установка отменена.')
            return
        try:
            profile = parse_link(link)
            break
        except ValueError as error:
            print(error, file=sys.stderr)
    net['vps'] = profile['vps']
    print(f"Выход через {net['vps']}:{profile['port']}. Будут установлены Xray, Pi-hole, правила IPv4 и home-net.")
    if args.plan:
        print('Предпросмотр завершён. Для установки запустите sudo python3 install.py.')
        return
    with tempfile.TemporaryDirectory(prefix='home-vpn-stage-') as directory:
        stage = Path(directory)
        stage_files(stage, net, profile)
        fresh_host(stage, net)
        if input('Установить на этот домашний сервер? [да/Нет] ').strip().lower() != 'да':
            print('Установка отменена.')
            return
        try:
            install(stage, net)
        except (Exception, KeyboardInterrupt) as cause:
            if STATE.exists():
                print('Установка прервана. Откатываю компоненты шлюза.', file=sys.stderr, flush=True)
                try:
                    uninstall()
                except (OSError, subprocess.CalledProcessError) as rollback_error:
                    raise ValueError(f'{cause}. Откат прерван: {rollback_error}. После устранения ошибки повторите '
                                     f'sudo python3 {BASE}/install.py --uninstall') from None
            raise
    print(f"На одном клиенте задайте шлюз и DNS {net['ip']}. Проверьте внешний IPv4 и открытие сайтов.")
    print(f"Для всей сети укажите этот же IP в DHCP роутера. Шлюз самого сервера — {net['router']}.")
    print(f"Панель Pi-hole: http://{net['ip']}:8080/admin/ · пароль: sudo cat {PRIVATE}/.env")
    print(f'Удаление с сохранением данных: sudo python3 {BASE}/install.py --uninstall')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, EOFError, KeyboardInterrupt) as error:
        sys.exit(f'Установка не завершена. {error or "Операция прервана."}')
