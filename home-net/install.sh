#!/bin/bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo 'Run the installer with sudo.' >&2
    exit 1
fi
utility_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for executable in python3 curl iptables systemctl systemd-analyze sudo; do
    command -v "$executable" >/dev/null
done
if systemctl is-active --quiet home-gateway-direct.service; then
    echo 'Switch back to VPN mode before updating home-net.' >&2
    exit 1
fi
python3 -c 'import ast,pathlib,sys; [ast.parse(pathlib.Path(p).read_text(), filename=p) for p in sys.argv[1:]]' \
    "$utility_dir/home-net" "$utility_dir/direct_mode.py" "$utility_dir/watchdog.py" "$utility_dir/notify.py"
install -d /usr/local/libexec
install -m 755 "$utility_dir/home-net" /usr/local/bin/home-net
install -m 755 "$utility_dir/direct_mode.py" /usr/local/libexec/home-gateway-direct.py
install -m 755 "$utility_dir/watchdog.py" /usr/local/libexec/home-net-watchdog.py
install -m 755 "$utility_dir/notify.py" /usr/local/libexec/home-net-notify.py
install -m 644 "$utility_dir/home-gateway-direct.service" /etc/systemd/system/home-gateway-direct.service
install -m 644 "$utility_dir/home-net-watchdog.service" /etc/systemd/system/home-net-watchdog.service
install -m 644 "$utility_dir/home-net-watchdog.timer" /etc/systemd/system/home-net-watchdog.timer
install -m 644 "$utility_dir/home-net-notify.service" /etc/systemd/system/home-net-notify.service
install -m 644 "$utility_dir/home-net-notify.timer" /etc/systemd/system/home-net-notify.timer
if [ ! -e /etc/default/home-gateway-direct ]; then
    install -m 644 "$utility_dir/defaults.env.example" /etc/default/home-gateway-direct
fi
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/home-gateway-direct.service /etc/systemd/system/home-net-watchdog.service /etc/systemd/system/home-net-watchdog.timer /etc/systemd/system/home-net-notify.service /etc/systemd/system/home-net-notify.timer
echo 'home-net installed. Check /etc/default/home-gateway-direct, then run: home-net status'
