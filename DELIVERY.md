# Передача проекта заказчику

## Что передавать

- исходный код проекта;
- `.env.example` как шаблон конфигурации;
- `README.md` и этот файл;
- при необходимости — отдельный экспорт БД без учётных данных и сессий.

Не передавайте `.env`, `data/`, `backend/uploads/`, `backend/max_session/`, файлы `*.session` и любые файлы диагностики. В них могут находиться пароли, токены или авторизованные сессии.

## Первый запуск (автоматически)

### Windows
```bash
setup.bat
```

### Linux / macOS
```bash
chmod +x setup.sh
./setup.sh
```

### Или вручную
```bash
cp .env.example .env
# Отредактируйте .env — задайте POSTGRES_PASSWORD, JWT_SECRET, прокси
docker compose up --build -d
```

**Миграции применяются автоматически** при старте контейнера `api`.

- Web: http://localhost:5000
- API: http://localhost:8000/docs

## Настройка платформ

После запуска откройте **http://localhost:5000/admin/settings** и введите:

- **VK** — User token или Service token
- **Telegram** — API ID + API HASH (или загрузите .session файл)
- **YouTube** — API ключ (необязательно, есть fallback)
- **TikTok** — работает без ключей через TikWM
- **Instagram** — нужен NON_RU_PROXY для прямого GraphQL
- **Dzen / OK** — нужен RU_PROXY

### Прокси

- **NON-RU proxy** — для TikTok, Instagram, Telegram (формат: `socks5://user:pass@host:port`)
- **RU proxy** — для Дзен, Одноклассники

**Важно:** Docker-контейнеры не наследуют VPN хост-машины. Если у вас VPN на весь компьютер, всё равно нужно указать прокси в настройках.

## Контроль перед запуском в работу

- Замените тестовые пароли и `JWT_SECRET` на уникальные значения.
- Ограничьте `CORS_ORIGINS` адресом клиентского интерфейса.
- Не публикуйте порты PostgreSQL и Redis в интернет без сетевой защиты.
- После передачи смените использованные при настройке пароли, API-токены и прокси-доступы.

## Проверка работоспособности

```bash
docker compose ps
docker compose logs api --tail=50
```

Все контейнеры должны иметь статус `Up`, а в логах `api` должно быть:
```
[entrypoint] Postgres is ready
[entrypoint] Running Alembic migrations...
[entrypoint] Starting API...
```
