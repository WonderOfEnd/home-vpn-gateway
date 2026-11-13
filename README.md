# home-vpn-gateway

Домашний шлюз Debian с Xray VLESS+REALITY, Pi-hole и точечной маршрутизацией
UDP. Репозиторий предназначен для конфигурации домашнего серверного шлюза
`home`. Сверено с работающим сервером 31 октября 2026 года.
[История и результат сверки](docs/audit-2026-10-31.md).

При сбое интернета: `ssh home home-net fix`. Проверка состояния:
`ssh home home-net status`. [Утилита home-net, аварийный прямой режим и установка](home-net/README.md).
[Разбор сбоя и проверки 13 ноября 2026](docs/incident-2026-11-13.md).

Адрес внешнего VPN-сервера, UUID клиента, ключ REALITY и MAC клиента LAN
заменены параметрами. Пароли, ключи доступа и локальные базы Pi-hole в Git
не сохраняются. Настройки внешнего VPN-сервера — отдельная предпосылка установки.

## Структура

| Путь | Назначение |
| --- | --- |
| `xray/config.json` | Обезличенный актуальный конфиг клиента Xray |
| `iptables/rules.txt` | Снимок IPv4-правил в формате iptables-restore |
| `systemd/`, `scripts/` | Xray, policy routing, исключения и правило Discord |
| `discord/` | Пример параметров MAC и LAN-интерфейса |
| `exceptions/` | Существующий LAN-интерфейс исключений сайтов |
| `pihole/`, `sysctl/` | Настройки DNS, Compose template и IPv4 forwarding |

## Маршрутизация

- На роутере DHCP-шлюз и DNS указывают на домашний сервер.
- DNS из LAN перенаправляется в Pi-hole. Единственный upstream —
  `127.0.0.1#5353`: Xray передаёт запросы через туннель.
- TCP из LAN поступает в `redirect-in` на порту 12345. Приватные адреса,
  российские назначения и пользовательские исключения идут напрямую;
  остальные соединения — через `proxy`.
- Обычный UDP остаётся прямым. Для четырёх адресов TruckersMP сохранён
  перехват через `XRAY_UDP`.
- Голос и трансляции нативного Discord выбранного ПК распознаются отдельным
  правилом и передаются в UDP-inbound Xray на порту 12346.
- Существующее правило FORWARD блокирует UDP 443 из LAN. Соединения приложений,
  способных повторить запрос по TCP, затем проходят обычный TCP-маршрут.

## Восстановление шлюза

1. Установить Xray с geodata, Docker, sudo, iptables-persistent и Pi-hole.
2. В копии `xray/config.json` заполнить `<VPS_IP>`, `<CLIENT_UUID>`,
   `<REALITY_SERVER_NAME>`, `<REALITY_PUBLIC_KEY>`, `<REALITY_SHORT_ID>` из своей
   панели x-ui. Используется отдельный VLESS/REALITY клиент на TCP 443 без flow.
   Проверить подготовленный конфиг через `xray run -test`.
3. Установить `systemd/xray.service`, его drop-in и две службы
   `xray-tproxy-*.service` в соответствующие пути `/etc/systemd/system/`.
4. Установить `scripts/xray-tproxy-rules.sh` в `/usr/local/bin/` с режимом 755.
   Этот скрипт восстанавливает fwmark 1 / table 100, предварительно убирая
   старое правило и содержимое данной таблицы.
5. В копии `iptables/rules.txt` заполнить `<VPS_IP>` и проверить имя LAN-интерфейса
   (`enp2s0` в снимке). Это полный снимок таблиц, включая существовавшие Docker
   chains и повторяющиеся live rules. Перед применением сохранить текущие правила.
6. Применить подготовленный файл через iptables-restore и сохранить средствами
   netfilter-persistent. Не загружать параллельно конкурирующий набор nftables.
7. Установить `sysctl/90-home-vpn-gateway.conf` в `/etc/sysctl.d/`, применить sysctl.
8. Выполнить daemon-reload, включить Xray и две службы policy routing.
9. Восстановить Pi-hole по [его настройкам](pihole/NOTES.md), затем DHCP шлюза/DNS.

Основной outbound `proxy` использует Mux: `concurrency: 256`,
`xudpConcurrency: 128`, `xudpProxyUDP443: allow`. Дополнительный `proxy-voice`
сохранён из live config, но текущие routing rules его не выбирают.

## Голос Discord

31 октября прямой UDP к назначенному голосовому серверу не отвечал, хотя
управляющее WebSocket-соединение работало. Через Xray получен корректный ответ
за 72–73 мс. Подтверждены RTC_CONNECTED голоса и трансляции; владелец подтвердил звук.

Правило использует [формат IP Discovery нативного Discord](https://docs.discord.com/developers/topics/voice-connections#ip-discovery):
UDP payload 74 байта, type 1, length 70. Для исходящих пакетов выбранного MAC
ставится conntrack mark `0x40000000`. Весь такой поток направляется TPROXY на
`127.0.0.1:12346`. IP голосовых серверов не фиксируются. Область работы — IPv4
и нативный клиент; браузерный WebRTC использует другой handshake.

Восстановление правила:

1. Установить `scripts/discord-voice-route.sh` в `/usr/local/bin/` с режимом 755.
2. Скопировать `discord/discord-voice-route.env.example` в
   `/etc/default/discord-voice-route`, задать реальные PC_MAC и LAN_IFACE.
3. В `systemd/discord-voice-route.service` заполнить USER и GROUP placeholders.
   На проверенном home у выбранного пользователя уже разрешён NOPASSWD-запуск
   `/usr/sbin/iptables`. Шаблон службы сам таких разрешений не создаёт.
4. Установить службу, выполнить daemon-reload и
   `systemctl enable --now discord-voice-route.service`.

Служба запускается после Xray, policy routing и netfilter-persistent;
перезапуск netfilter-persistent переустанавливает правило. Discord chain
исключена из статического rules.txt, поскольку ею управляет служба.

Проверка: `systemctl status discord-voice-route` и
`iptables -t mangle -L DISCORD_VOICE -n -v`. Откат: остановить и отключить
discord-voice-route.service; ExecStop удаляет только её собственную цепочку и hook.

## Исключения и журналы

LAN UI исключений работает на порту 8090 с HTTP Basic Auth. Домены хранятся
в `/etc/xray-exceptions.json`, пароль — в отдельном локальном файле. Для новой
установки список начинается с `[]`; личные исключения в шаблон не копировались.

С 27 октября у Xray `access: none`, `loglevel: warning`: журнал соединений
отключён, ошибки продолжают сохраняться в `/var/log/xray/error.log`.
Логирование Pi-hole этой правкой не менялось.
