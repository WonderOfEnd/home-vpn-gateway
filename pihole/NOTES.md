# Pi-hole домашнего шлюза

Сверено 31 октября 2026 года с работающим контейнером pihole.

- Настроен image `pihole/pihole:latest`; версия запущенного образа — `2026.07.2`.
- Network mode host; restart policy unless-stopped.
- dns.upstreams: только `127.0.0.1#5353`.
- dns.listeningMode: ALL.
- webserver.port: `8080o,8443os,[::]:8080o,[::]:8443os`.
- TZ контейнера: Europe/Moscow; сверка её не меняла.

Upstream и web ports находятся в pihole.toml в подключённом `/etc/pihole`,
а не обязательно в environment Compose. На чистой установке их задать явно.

`docker-compose.json` — допустимый для Docker Compose JSON-шаблон, собранный
по параметрам live container. В нём нет API-пароля и содержимого базы Pi-hole.

```sh
cp .env.example .env
# Указать свой PIHOLE_PASSWORD в .env.
docker compose --env-file .env -f docker-compose.json config -q
docker compose --env-file .env -f docker-compose.json up -d
docker exec pihole pihole-FTL --config dns.upstreams '["127.0.0.1#5353"]'
docker exec pihole pihole-FTL --config webserver.port '8080o,8443os,[::]:8080o,[::]:8443os'
```

Проверка без изменений:

```sh
docker exec pihole pihole-FTL --config dns.upstreams
docker exec pihole pihole-FTL --config webserver.port
docker exec pihole pihole status
```

При восстановлении существующей установки сначала вернуть её приватный
каталог данных. `etc-pihole` и `etc-dnsmasq.d` игнорируются Git. Наборы блоклистов
проверяются в самой Pi-hole; в этой сверке их база не экспортировалась.
