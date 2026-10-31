#!/usr/bin/env bash
# Route native Discord UDP voice flows from the gaming PC through home Xray.
# No server IPs or account credentials are stored here.
set -euo pipefail

IPT=/usr/sbin/iptables
PC_MAC="${PC_MAC:?Set PC_MAC to the gaming PC MAC address}"
LAN_IFACE="${LAN_IFACE:-enp2s0}"
CHAIN=DISCORD_VOICE
FLOW_MARK=0x40000000/0x40000000
DISCOVERY='0>>22&0x3C@4>>16=82&&0>>22&0x3C@8=0x00010046'

ipt() { sudo -n "$IPT" -w 5 -t mangle "$@"; }

entry=(-i "$LAN_IFACE" -p udp -m mac --mac-source "$PC_MAC"
       -m comment --comment 'Discord voice for gaming PC' -j "$CHAIN")
detect=(-m u32 --u32 "$DISCOVERY"
        -m comment --comment 'Discord IP discovery'
        -j CONNMARK --set-xmark "$FLOW_MARK")
route=(-p udp -m connmark --mark "$FLOW_MARK"
       -m comment --comment 'Discord voice marked flow'
       -j TPROXY --on-port 12346 --on-ip 127.0.0.1 --tproxy-mark 0x1/0x1)

case "${1:-install}" in
    install)
        # These are created by the existing Xray routing services.
        ipt -n -L XRAY_UDP >/dev/null
        /usr/sbin/ip route show table 100 | /usr/bin/grep -q '^local default dev lo'
        if ! ipt -n -L "$CHAIN" >/dev/null 2>&1; then
            ipt -N "$CHAIN"
        fi
        if ! ipt -C "$CHAIN" "${detect[@]}" 2>/dev/null; then
            ipt -A "$CHAIN" "${detect[@]}"
        fi
        if ! ipt -C "$CHAIN" "${route[@]}" 2>/dev/null; then
            ipt -A "$CHAIN" "${route[@]}"
        fi
        if ! ipt -C PREROUTING "${entry[@]}" 2>/dev/null; then
            ipt -I PREROUTING 1 "${entry[@]}"
        fi
        echo 'Discord native voice routing is installed.'
        ;;
    remove)
        while ipt -C PREROUTING "${entry[@]}" 2>/dev/null; do
            ipt -D PREROUTING "${entry[@]}"
        done
        if ipt -n -L "$CHAIN" >/dev/null 2>&1; then
            ipt -F "$CHAIN"
            ipt -X "$CHAIN"
        fi
        echo 'Discord native voice routing is removed.'
        ;;
    *)
        echo 'Usage: discord-voice-route.sh [install|remove]' >&2
        exit 2
        ;;
esac
