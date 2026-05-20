# Podkop List Updater

Это репозиторий, который каждый день собирает списки доменов и подсетей для `podkop`.

На выходе всегда есть 4 набора:

- `podkop-russia-domains`
- `podkop-russia-subnets`
- `podkop-foreign-domains`
- `podkop-foreign-subnets`

Сборка идёт из нескольких слоёв:

- ручные seed-списки
- готовые сервисные списки
- geosite-source файлы из `v2fly/domain-list-community`
- autodiscovery через бесплатные внешние источники

Идея простая: руками держим только базу, всё остальное стараемся подтягивать автоматически.

## Что где лежит

- [config/sources.json](/Users/rendfoxy/Documents/автоскрипт/config/sources.json) — главный конфиг сборки
- [config/manual/podkop-russia-seed.txt](/Users/rendfoxy/Documents/автоскрипт/config/manual/podkop-russia-seed.txt) — ручная база для российского маршрута
- [config/manual/podkop-foreign-seed.txt](/Users/rendfoxy/Documents/автоскрипт/config/manual/podkop-foreign-seed.txt) — ручная база для иностранного маршрута
- [config/manual/podkop-foreign-roots.txt](/Users/rendfoxy/Documents/автоскрипт/config/manual/podkop-foreign-roots.txt) — root-домены для autodiscovery
- [config/manual/podkop-foreign-crtsh-roots.txt](/Users/rendfoxy/Documents/автоскрипт/config/manual/podkop-foreign-crtsh-roots.txt) — точечные root-домены для `crt.sh`
- [scripts/build_podkop_lists.py](/Users/rendfoxy/Documents/автоскрипт/scripts/build_podkop_lists.py) — сама сборка
- [src](/Users/rendfoxy/Documents/автоскрипт/src) — готовые файлы
- [.github/workflows/update-podkop-lists.yml](/Users/rendfoxy/Documents/автоскрипт/.github/workflows/update-podkop-lists.yml) — daily workflow

## Что именно собирается

### Russia

- `podkop-russia-domains` — домены, которые должны идти через российский маршрут
- `podkop-russia-subnets` — подсети для российского маршрута

### Foreign

- `podkop-foreign-domains` — домены, которые должны идти через иностранный маршрут
- `podkop-foreign-subnets` — подсети для иностранного маршрута

Для `foreign-domains` сейчас дополнительно подключены:

- `HODCA` и сервисные списки из `allow-domains`
- geosite-source файлы из `v2fly/domain-list-community`
- AI и CDN/hosting категории вроде `OpenAI`, `Anthropic`, `Cloudflare`, `DigitalOcean`, `Hetzner`, `Meta`, `Telegram`, `TikTok`

Для `foreign-subnets` отдельно тянутся официальные и сервисные IPv4-источники для `Telegram`, `Cloudflare`, `AWS/CloudFront`, `DigitalOcean`, `Hetzner`, `OVH`, `Meta`, `Twitter`.

Это полезно, потому что такие списки часто обновляются и дают покрытие даже тогда, когда discovery API временно тупят или режут rate limit.

## Autodiscovery

Автодобор включён только там, где он реально нужен и даёт пользу.

Сейчас используются:

- `urlscan.io` — основной бесплатный источник
- `crt.sh` — точечно для отдельных AI-веток

Если добавить `URLSCAN_API_KEY` в GitHub Secrets, `urlscan` работает заметно стабильнее.

## Формат для podkop

По документации `podkop` внешние списки можно подключать в форматах `.json`, `.srs`, `.lst`, `.txt`:

- [Podkop Sections](https://podkop.net/docs/sections/)

Этот репозиторий публикует:

- `.lst` — одна запись на строку
- `.json` — rule-set в совместимом формате:
  - домены через `domain_suffix`
  - подсети через `ip_cidr`

То есть по формату здесь всё нормально для `podkop`.

## Откуда брать готовые файлы

Есть два варианта.

### 1. GitHub Releases

Это самый удобный вариант, если нужна всегда свежая версия по стабильной ссылке.

- [podkop-foreign-domains.lst](https://github.com/Rendfoxy/podkop-list-updater/releases/latest/download/podkop-foreign-domains.lst)
- [podkop-foreign-subnets.lst](https://github.com/Rendfoxy/podkop-list-updater/releases/latest/download/podkop-foreign-subnets.lst)
- [podkop-russia-domains.lst](https://github.com/Rendfoxy/podkop-list-updater/releases/latest/download/podkop-russia-domains.lst)
- [podkop-russia-subnets.lst](https://github.com/Rendfoxy/podkop-list-updater/releases/latest/download/podkop-russia-subnets.lst)

При желании можно брать и `.json`-версии из того же `latest` release.

### 2. Файлы из `src/`

Если работаешь локально, итоговые файлы всегда лежат в [src](/Users/rendfoxy/Documents/автоскрипт/src).

## Как запустить локально

```bash
python3 scripts/build_podkop_lists.py
```

После сборки обновятся:

- `src/<name>.lst`
- `src/<name>.json`
- `src/manifest.json`

## Что делает workflow

GitHub Actions каждый день:

1. проверяет Python-файлы
2. запускает тесты
3. собирает списки
4. коммитит обновления, если они есть
5. обновляет `latest` release с готовыми файлами

## Если хочешь поменять логику

Обычно правится одно из трёх:

- [config/sources.json](/Users/rendfoxy/Documents/автоскрипт/config/sources.json) — если нужно добавить или убрать внешние источники
- `config/manual/*.txt` — если нужно поправить ручную базу
- [scripts/build_podkop_lists.py](/Users/rendfoxy/Documents/автоскрипт/scripts/build_podkop_lists.py) — если нужно менять саму механику сборки

Если коротко: это не “один статичный список”, а маленький сборщик, который старается держать `podkop`-файлы живыми без постоянного ручного копания.
