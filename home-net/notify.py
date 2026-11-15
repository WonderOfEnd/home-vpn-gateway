#!/usr/bin/python3
"""Observe gateway mode changes and deliver a persistent ntfy queue independently."""
from datetime import datetime
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys

CONFIG = Path('/etc/home-net/ntfy.json')
DIRECT_UNIT = 'home-gateway-direct.service'
STATE_DIR = Path('/var/lib/home-net-notify')
HOST = 'ntfy.sh'


def mode():
    result = subprocess.run(['systemctl', 'is-active', DIRECT_UNIT],
                            capture_output=True, text=True, timeout=3)
    status = result.stdout.strip()
    if status == 'active':
        return 'direct'
    if status in ('inactive', 'failed'):
        return 'vpn'
    return None  # Ignore the brief interval while rules are being switched.


def observe(state, current, timestamp, test=False):
    queue = state.setdefault('queue', [])
    previous = state.get('mode')
    if current is not None:
        if previous in ('vpn', 'direct') and previous != current:
            queue.append({'mode': current, 'time': timestamp, 'test': False})
        state['mode'] = current
    if test:
        queue.append({'mode': current, 'time': timestamp, 'test': True})
    return state


def payload(topic, event):
    if event['test']:
        message = 'Тест: личные уведомления о переключениях home подключены.'
    elif event['mode'] == 'direct':
        message = 'VPN-шлюз выключен. Включён прямой интернет без VPN и фильтрации Pi-hole.'
    else:
        message = 'VPN-шлюз включён. Интернет снова идёт через VPN, фильтрация Pi-hole включена.'
    return {'topic': topic, 'title': 'Home VPN',
            'message': message + '\nСобытие: ' + event['time'],
            'priority': 4 if event['mode'] == 'direct' and not event['test'] else 3,
            'tags': ['white_check_mark' if event['mode'] == 'vpn' else 'warning']}


def publish(topic, event):
    # Public DNS and a direct HTTPS connection avoid dependence on Xray/Pi-hole DNS.
    query = subprocess.run(['dig', '@1.1.1.1', HOST, 'A', '+short', '+time=2', '+tries=1'],
                           capture_output=True, text=True, timeout=3)
    addresses = []
    for line in query.stdout.splitlines():
        try:
            address = ipaddress.IPv4Address(line.strip())
            if address.is_global:
                addresses.append(str(address))
        except ipaddress.AddressValueError:
            continue
    if query.returncode or not addresses:
        return False
    result = subprocess.run(
        ['curl', '--ipv4', '--noproxy', '*', '--silent', '--show-error', '--fail',
         '--connect-timeout', '3', '--max-time', '5',
         '--resolve', HOST + ':443:' + ','.join(addresses),
         '--header', 'Content-Type: application/json', '--data-binary', '@-',
         '--output', '/dev/null', '--write-out', '%{http_code}', 'https://' + HOST + '/'],
        input=json.dumps(payload(topic, event), ensure_ascii=False),
        capture_output=True, text=True, timeout=7)
    return result.returncode == 0 and result.stdout.strip().startswith('2')


def save(state):
    temporary = STATE_DIR / 'state.tmp'
    with temporary.open('w') as stream:
        json.dump(state, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(STATE_DIR / 'state.json')


def main(test=False):
    os.umask(0o077)
    config = json.loads(CONFIG.read_text())
    topic = config['topic']
    if not isinstance(topic, str) or not re.fullmatch(r'[A-Za-z0-9_-]{24,128}', topic):
        raise ValueError('Use a long random ntfy topic')
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE_DIR / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = STATE_DIR / 'state.json'
        state = json.loads(path.read_text()) if path.exists() else {}
        current = mode()
        observe(state, current, datetime.now().astimezone().isoformat(timespec='seconds'), test)
        save(state)  # Save the event before making an unreliable network request.
        queue = state['queue']
        if queue:
            try:
                delivered = publish(topic, queue[0])
            except (OSError, subprocess.TimeoutExpired):
                delivered = False
            if delivered:
                queue.pop(0)
                save(state)
                print('Notification accepted; pending:', len(queue), flush=True)
            else:
                print('Notification pending; will retry with Internet available.', flush=True)
    return 0


if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--test']):
        raise SystemExit('Usage: home-net-notify.py [--test]')
    sys.exit(main(test=sys.argv[1:] == ['--test']))
