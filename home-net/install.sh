#!/bin/bash
set -euo pipefail

stage=
if [[ $# == 2 && $1 == --stage && $2 == /* && -d $2 ]]; then
    stage="$(realpath -e -- "$2")"
    if [[ $stage == / ]]; then
        echo 'The staging directory must be separate from the live system.' >&2
        exit 2
    fi
elif [[ $# != 0 ]]; then
    echo 'Usage: install.sh [--stage ABSOLUTE_DIRECTORY]' >&2
    exit 2
fi
if [[ -z $stage && $(id -u) -ne 0 ]]; then
    echo 'Run the installer with sudo.' >&2
    exit 1
fi
utility_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z $stage ]]; then
    for executable in python3 curl iptables systemctl systemd-analyze sudo; do
        command -v "$executable" >/dev/null
    done
    if systemctl is-active --quiet home-gateway-direct.service; then
        echo 'Switch back to VPN mode before updating home-net.' >&2
        exit 1
    fi
fi
python3 -c 'import ast,pathlib,sys; [ast.parse(pathlib.Path(p).read_text(), filename=p) for p in sys.argv[1:]]' \
    "$utility_dir/home-net" "$utility_dir/direct_mode.py" "$utility_dir/watchdog.py" "$utility_dir/notify.py"
mkdir -p -- "$stage/usr/local/libexec" "$stage/usr/local/bin" "$stage/etc/systemd/system" "$stage/etc/default"
install -m 755 "$utility_dir/home-net" "$stage/usr/local/bin/home-net"
install -m 755 "$utility_dir/direct_mode.py" "$stage/usr/local/libexec/home-gateway-direct.py"
install -m 755 "$utility_dir/watchdog.py" "$stage/usr/local/libexec/home-net-watchdog.py"
install -m 755 "$utility_dir/notify.py" "$stage/usr/local/libexec/home-net-notify.py"
for unit in home-gateway-direct.service home-net-{watchdog,notify}.{service,timer}; do
    install -m 644 "$utility_dir/$unit" "$stage/etc/systemd/system/$unit"
done
if [[ ! -e $stage/etc/default/home-gateway-direct ]]; then
    install -m 644 "$utility_dir/defaults.env.example" "$stage/etc/default/home-gateway-direct"
fi
[[ -z $stage ]] || exit 0
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/home-gateway-direct.service /etc/systemd/system/home-net-watchdog.service /etc/systemd/system/home-net-watchdog.timer /etc/systemd/system/home-net-notify.service /etc/systemd/system/home-net-notify.timer
echo 'home-net installed. Check /etc/default/home-gateway-direct, then run: home-net status'
