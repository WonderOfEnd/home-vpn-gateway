#!/bin/bash
# Включает штатное усыпление ВМ при выключении ПК (libvirt-guests). Запуск: sudo bash ~/pcstate-root.sh
set -euo pipefail
CONF=/etc/sysconfig/libvirt-guests
[ -e "$CONF" ] && cp -a "$CONF" "$CONF.bak-pcstate"   # бэкап, если конфиг уже был
cat > "$CONF" <<CFG
ON_BOOT=ignore
ON_SHUTDOWN=suspend
SHUTDOWN_TIMEOUT=120
CFG
# --now: сервис должен быть активен, иначе его ExecStop не сработает при выключении; ON_BOOT=ignore — ВМ сами не стартуют
systemctl enable --now libvirt-guests.service
systemctl is-active libvirt-guests.service
echo "Готово. Откат: systemctl disable --now libvirt-guests; rm $CONF (или mv $CONF.bak-pcstate $CONF)"
