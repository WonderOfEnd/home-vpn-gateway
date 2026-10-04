# Конфиг Pi-hole

Сам Pi-hole работает без изменений (Docker, `pihole/pihole:latest`,
`--network host`) — ничего кастомного, кроме одной настройки.

## Upstream DNS

Upstream у Pi-hole указывает на локальный DNS-релей xray, а не напрямую на
публичный резолвер:

```
pihole-FTL --config dns.upstreams '["127.0.0.1#5353"]'
```

См. инбаунд `dns-in` в `xray/config.json` (порт 5353) — он пересылает
каждый запрос через outbound `proxy` (туннель VLESS/REALITY), так что
резолв DNS происходит как будто с внешнего сервера. Это фикс для подмены
DNS на уровне провайдера (зафиксировано напрямую: прямой запрос к `8.8.8.8`
на заблокированный домен вернул `NXDOMAIN` с выставленным флагом `aa` —
публичный резолвер никогда так не отвечает для домена, которым не
управляет, именно так и была поймана подмена).

## Пример запуска в Docker

```
docker run -d --name pihole \
  --network host \
  -e TZ=<ваша таймзона> \
  -e FTLCONF_dns_listeningMode=ALL \
  -v pihole-etc:/etc/pihole \
  --restart unless-stopped \
  pihole/pihole:latest
```

(`FTLCONF_webserver_api_password` задаётся отдельно — здесь не хранится.)

## Блоклисты

Помимо StevenBlack, подключены: hagezi `adblock/pro.txt` и RU AdList
(`ElkyBoy/ruadlist-pihole`). Список hagezi `hosts/` и `domains/` устарел, использовать
только `adblock/`. Перестроить: `docker exec pihole pihole -g`.
