# Content Tracker

Платформа учёта контент-публикаций с агрегированной метрикой **Si** (сумма реакций: лайки + репосты + комментарии + сохранения) по ссылкам на посты в соцсетях.

## Роли
- **org_user** — видит и управляет только публикациями своей организации.
- **admin** — видит всех пользователей/публикации, дашборды, рейтинг организаций.

## Стек
- Backend: FastAPI, SQLAlchemy 2.0 (async), Alembic, PostgreSQL, Redis, Celery (worker + beat)
- Frontend: Next.js 14 (App Router), TypeScript, Tailwind, TanStack Query, Recharts
- Реалтайм: WebSocket (FastAPI) + Redis pub/sub между Celery-воркером и API
- Деплой: Docker Compose (postgres, redis, api, worker, beat, web)

## Запуск

### Автоматически (рекомендуется)

**Windows:**
```bash
setup.bat
```

**Linux / macOS:**
```bash
chmod +x setup.sh
./setup.sh
```

### Вручную
```bash
cp .env.example .env
# Отредактируйте .env — задайте POSTGRES_PASSWORD, JWT_SECRET, прокси
docker compose up --build -d
```

**Миграции применяются автоматически** при старте контейнера `api`.

- API: http://localhost:8000/docs
- Web: http://localhost:5000

## Парсеры платформ

### VK
- Требуется `VK_USER_TOKEN` или `VK_SERVICE_TOKEN` (настраивается в UI).
- Поддерживает посты (`wall.getById`), видео и клипы (`video.get`).
- HTML fallback без токена.

### Telegram
- Через **Telethon** (MTProto) — собирает просмотры, реакции, репосты, комментарии.
- Требуется `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` + файл сессии.
- Без Telethon — публичная превью `t.me/s/` (только просмотры и репосты).

### YouTube
- Через публичный API (mixerno.space) — без ключей.
- Собирает лайки, просмотры, комментарии.

### TikTok
- **TikWM** (основной) — бесплатный API, без ключей.
- Собирает views, likes, comments, shares, saves.
- Fallback: RapidAPI.

### Instagram
- **Reels**: Calcxi (бесплатно) — views, likes, comments, shares, saves.
- **Посты/карусели**: Прямой GraphQL запрос — точные likes, comments.
- Fallback: публичный HTML / Playwright, без Instagram-аккаунтов и токенов.

### Dzen
- Статьи: Playwright — likes, views, comments.
- Shorts: Playwright — likes, comments.

### OK (Одноклассники)
- Видео: Playwright — likes, views, comments, reposts.

### MAX (max.ru)
- Через PyMAX API или headless Chromium.
- Требуется авторизация через UI или файл сессии.

## Настройка доступов к платформам (UI)

Админ может менять ключи, токены и прокси в интерфейсе: **http://localhost:5000/admin/settings**

### Прокси
- **NON-RU proxy** — для TikTok, Instagram, Telegram (формат: `socks5://user:pass@host:port`)
- **RU proxy** — для Дзен, Одноклассники

**Важно:** Docker-контейнеры не наследуют VPN хост-машины. Если у вас VPN на весь компьютер, всё равно нужно указать прокси в настройках.

### VK
- Переключатель между User token и Service token.

### Telegram
- **Через телефон**: API ID + API HASH → номер → код → 2FA.
- **Загрузить сессию**: загрузка .session/.txt файла.

### MAX
- **Через телефон**: номер → SMS код → пароль 2FA.
- **Загрузить сессию**: указать путь к файлу сессии.

## Защита
- Rate limiting: 5 попыток входа за 15 минут, 100 запросов в минуту.
- JWT авторизация с refresh token.
- Региональная изоляция данных (org_user видит только свои публикации).

## Структура
```
backend/          FastAPI приложение, парсеры, воркеры Celery, Alembic-миграции
frontend/         Next.js приложение (login, messages CRUD, admin)
docker-compose.yml
.env.example
```
