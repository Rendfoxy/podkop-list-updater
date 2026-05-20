# Podkop List Updater

> [!WARNING]
> **ОТКАЗ ОТ ОТВЕТСТВЕННОСТИ**
>
> Этот репозиторий публикует и актуализирует списки доменов и подсетей исключительно в образовательных, исследовательских и справочных целях.
> Авторы и сопровождающие не дают гарантий полноты, точности, пригодности или безошибочной работы этих данных в любой конкретной среде.
> Любое использование материалов из этого репозитория осуществляется пользователем на свой риск и под его собственную ответственность.
> Авторы и сопровождающие не несут ответственности за любые прямые, косвенные, случайные, специальные, штрафные, сопутствующие или иные убытки, расходы, простой, потерю данных, потерю доступа, потерю прибыли или иные последствия, возникшие в связи с использованием, невозможностью использования или интерпретацией этих данных, даже если о возможности таких последствий было заранее известно или отдельно указано.
> Используя этот репозиторий, вы самостоятельно оцениваете правовые, технические и организационные последствия работы с опубликованными данными.

Это репозиторий, который регулярно собирает и обновляет списки доменов и подсетей для `podkop`.

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

- [config/sources.json](config/sources.json) — главный конфиг сборки
- [config/manual/podkop-russia-seed.txt](config/manual/podkop-russia-seed.txt) — ручная база для набора `russia`
- [config/manual/podkop-foreign-seed.txt](config/manual/podkop-foreign-seed.txt) — ручная база для набора `foreign`
- [config/manual/podkop-foreign-roots.txt](config/manual/podkop-foreign-roots.txt) — root-домены для autodiscovery
- [config/manual/podkop-foreign-crtsh-roots.txt](config/manual/podkop-foreign-crtsh-roots.txt) — точечные root-домены для `crt.sh`
- [config/manual/podkop-foreign-resolve-roots.txt](config/manual/podkop-foreign-resolve-roots.txt) — домены для `DNS -> /32` слоя
- [scripts/build_podkop_lists.py](scripts/build_podkop_lists.py) — сама сборка
- [src](src) — готовые файлы
- [.github/workflows/update-podkop-lists.yml](.github/workflows/update-podkop-lists.yml) — workflow обновления

## Что именно собирается

### Набор `russia`

- `podkop-russia-domains` — доменный список категории `russia`
- `podkop-russia-subnets` — список подсетей категории `russia`

### Набор `foreign`

- `podkop-foreign-domains` — доменный список категории `foreign`
- `podkop-foreign-subnets` — список подсетей категории `foreign`

Для `podkop-foreign-domains` сейчас дополнительно подключены:

- `HODCA` и сервисные списки из `allow-domains`
- geosite-source файлы из `v2fly/domain-list-community`
- AI и CDN/hosting категории вроде `OpenAI`, `Anthropic`, `Cloudflare`, `DigitalOcean`, `Hetzner`, `Meta`, `Telegram`, `TikTok`

Для `podkop-foreign-subnets` отдельно тянутся официальные и сервисные IPv4-источники для `Telegram`, `Cloudflare`, `AWS/CloudFront`, `DigitalOcean`, `Hetzner`, `OVH`, `Meta`, `Twitter`, а также ASN-источники там, где это оправдано.

Это полезно, потому что такие списки часто обновляются и дают покрытие даже тогда, когда discovery API временно тупят или режут rate limit.

## Autodiscovery

Автодобор включён только там, где он реально нужен и даёт пользу.

Сейчас используются:

- `urlscan.io` — основной бесплатный источник
- `crt.sh` — точечно для отдельных AI-веток

Если добавить `URLSCAN_API_KEY` в GitHub Secrets, `urlscan` работает заметно стабильнее.

## Устойчивость к сбоям источников

Для критичных upstream-источников в проекте есть кеш последней удачной версии.

Сейчас это работает для:

- `Telegram`
- `Cloudflare`
- `AWS`
- ASN-источников для части `foreign-subnets`

Если внешний источник временно не отвечает, сборщик использует последнюю успешную копию вместо того, чтобы отдавать пустой или урезанный список.

## Формат для podkop

По документации `podkop` внешние списки можно подключать в форматах `.json`, `.srs`, `.lst`, `.txt`:

- [Podkop Sections](https://podkop.net/docs/sections/)

Этот репозиторий публикует:

- `.lst` — одна запись на строку
- `.json` — rule-set в совместимом формате:
  - домены через `domain_suffix`
  - подсети через `ip_cidr`

То есть по формату здесь всё сведено к нормальному внешнему списку для `podkop`.

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

Если работаешь локально, итоговые файлы всегда лежат в [src](src).

## Как запустить локально

```bash
python3 scripts/build_podkop_lists.py
```

После сборки обновятся:

- `src/<name>.lst`
- `src/<name>.json`
- `src/manifest.json`

## Что делает workflow

GitHub Actions регулярно:

1. проверяет Python-файлы
2. запускает тесты
3. собирает списки
4. коммитит обновления, если они есть
5. обновляет `latest` release с готовыми файлами

Сейчас workflow запускается каждые 6 часов. Плюс его всегда можно запустить руками через `Run workflow`.

## Если хочешь поменять логику

Обычно правится одно из трёх:

- [config/sources.json](config/sources.json) — если нужно добавить или убрать внешние источники
- `config/manual/*.txt` — если нужно поправить ручную базу
- [scripts/build_podkop_lists.py](scripts/build_podkop_lists.py) — если нужно менять саму механику сборки

Если коротко: это не статичный набор файлов, а сборщик, который старается держать списки актуальными без постоянной ручной правки.

## Лицензия

Материалы этого репозитория распространяются на условиях лицензии `CC BY-NC 4.0`.

Это значит:

- использовать, копировать и адаптировать материалы можно свободно
- обязательна ссылка на источник
- коммерческое использование без отдельного письменного разрешения не допускается

Текст лицензии лежит в [LICENSE](LICENSE).
