# Podkop list updater

Этот проект каждый день собирает свежие списки доменов и подсетей для `podkop` и складывает их в папку `src/`.
Логика разделена на 4 внешних списка:

- `russia-domains`
- `russia-subnets`
- `foreign-domains`
- `foreign-subnets`

## Что внутри

- `config/sources.json` - какие списки тянуть, какого они типа и как называть готовые файлы
- `config/manual/podkop-russia-seed.txt` - основной seed для маршрутизации через российские серверы
- `config/manual/podkop-foreign-seed.txt` - основной seed для маршрутизации через иностранные серверы
- `config/manual/podkop-russia-roots.txt` - запасной набор root-доменов, если позже понадобится autodiscovery для russian-профиля
- `config/manual/podkop-foreign-roots.txt` - root-домены для автодобора поддоменов через внешние passive-источники
- `config/manual/podkop-foreign-crtsh-roots.txt` - точечные AI-root'ы для более глубокого CT-поиска
- `scripts/build_podkop_lists.py` - сборка, валидация, дедупликация и генерация файлов
- `src/` - готовые `.lst` и `.json`, которые можно отдавать в `podkop`
- `.github/workflows/update-podkop-lists.yml` - ежедневный запуск в GitHub Actions

## Автодобор

Для `foreign-domains` включен autodiscovery новых поддоменов по root-доменам.
Сейчас по умолчанию используются два источника:

- `urlscan.io` для свежих публично замеченных поддоменов
- `crt.sh` точечно для AI-веток, где нужен более глубокий certificate transparency поиск

- сборка больше не зависит от одного rate-limited API
- в `src/manifest.json` видно, сколько записей пришло из `remote`, `local` и `discovery`
- если добавить `URLSCAN_API_KEY` в GitHub Secrets, `urlscan`-слой станет заметно стабильнее и меньше будет упираться в `429`

Дополнительно для `foreign-domains` подключены бесплатные service-списки из `v2fly/domain-list-community`:

- `openai`
- `telegram`
- `tiktok`

Они усиливают покрытие даже без discovery API и особенно полезны, когда внешние passive-источники временно режут rate limit.

## Как использовать

1. Отредактируйте `config/sources.json`.
2. При необходимости добавьте свои домены или подсети в `config/manual/*.txt`.
3. Запустите локально:

```bash
python3 scripts/build_podkop_lists.py
```

После сборки появятся файлы для каждого выхода:

- `src/<name>.lst`
- `src/<name>.json`

Для `podkop` можно использовать raw-ссылку на любой из них.

## Стартовый профиль

По умолчанию уже настроен сбор:

- `podkop-russia-domains`: `Russia/inside-raw.lst` + часть сервисных allow-domains + `podkop-russia-seed.txt`
- `podkop-russia-subnets`: `podkop-russia-seed.txt`
- `podkop-foreign-domains`: сервисные allow-domains для Telegram/TikTok/Meta/Twitter/Google AI + `podkop-foreign-seed.txt`
- `podkop-foreign-domains`: дополнительно делает autodiscovery поддоменов по `podkop-foreign-roots.txt`
- `podkop-foreign-subnets`: официальный `Telegram CIDR` + официальный `Cloudflare ips-v4` + `podkop-foreign-seed.txt`

На выходе сейчас формируются:

- `podkop-russia-domains`
- `podkop-russia-subnets`
- `podkop-foreign-domains`
- `podkop-foreign-subnets`

Если нужен другой набор, просто поменяйте URL в `config/sources.json`.
