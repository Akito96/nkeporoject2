# Кофейня — веб-приложение на FastAPI и PostgreSQL

Полнофункциональное веб-приложение кофейни: каталог, корзина, транзакционное оформление заказов, PDF-чеки с кириллицей и QR-кодом, блог на Markdown с защитой от XSS, админ-панель, аналитика продаж на Chart.js и доска drag-and-drop стикеров.

## Стек

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async / `asyncpg`), Alembic, Pydantic v2
- **БД:** PostgreSQL 16
- **Auth и безопасность:** JWT в `httpOnly` cookie (`SameSite=Lax`), `bcrypt`, CSRF-токен, `nh3` (очистка HTML от XSS)
- **Фронтенд:** Jinja2, CSS-переменные (тёплая палитра, WCAG AA), vanilla JS, Chart.js
- **PDF-чеки:** ReportLab + DejaVuSans + встроенный QR-код
- **Инфраструктура:** Docker (multi-stage), Gunicorn + Uvicorn workers, Nginx, Let's Encrypt, GitHub Actions (`ruff` + `pytest`)

## Локальный запуск (Docker Compose)

В **Git Bash** (или Linux/macOS):

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec app alembic upgrade head
docker compose exec app python -m app.seed
```

В **PowerShell** замените первую команду на `Copy-Item .env.example .env`.

### Основные адреса

| Раздел | URL |
|---|---|
| Каталог | http://localhost:8000/products |
| Блог | http://localhost:8000/blog |
| Вход / Регистрация | http://localhost:8000/auth/login · http://localhost:8000/auth/register |
| Корзина и заказы | http://localhost:8000/cart · http://localhost:8000/orders |
| Админ-панель | http://localhost:8000/admin |
| Аналитика (Chart.js) | http://localhost:8000/admin/stats |
| Доска стикеров | http://localhost:8000/admin/stickers |
| Swagger UI / Health | http://localhost:8000/docs · http://localhost:8000/health |

### Тестовые учётные записи (после `app.seed`)

- **Администратор:** `admin@coffee.local` / `AdminPassword123!`
- **Гость:** `user@coffee.local` / `UserPassword123!`

## Тесты и линтер

```bash
# Модульные тесты и линтер
docker compose exec app pytest -q
docker compose exec app ruff check .

# Включая сквозной E2E-тест на реальной PostgreSQL БД (осторожно: очищает указанную тестовую БД!)
docker compose exec -e TEST_DATABASE_URL="postgresql+asyncpg://coffee_user:change_me_in_production@db:5432/coffee_shop" app pytest -q
```

В GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) на каждый `push` и `pull_request` автоматически поднимается PostgreSQL 16, проверяется `ruff check .`, применяются миграции `alembic upgrade head` и запускается весь набор `pytest -q`.

## Продакшн-деплой (Nginx + HTTPS Let's Encrypt)

1. На сервере создайте `.env` из `.env.example` и задайте надёжные `POSTGRES_PASSWORD`, `SECRET_KEY` (>= 32 символа), `COOKIE_SECURE=true`, `DEBUG=false`, `DOMAIN=your-domain.com`.
2. Замените `coffee.example.com` на ваш домен в `deploy/nginx/coffee.conf`.
3. Выпустите сертификат Let's Encrypt (первый запуск):
   ```bash
   docker compose -f docker-compose.prod.yml run --rm certbot certonly \
     --webroot --webroot-path /var/www/certbot \
     -d your-domain.com --email admin@your-domain.com --agree-tos --no-eff-email
   ```
4. Запустите продакшн-стек и примените миграции:
   ```bash
   docker compose -f docker-compose.prod.yml up --build -d
   docker compose -f docker-compose.prod.yml exec app alembic upgrade head
   ```
5. Для автопродления сертификатов добавьте в `crontab`:
   ```cron
   0 3 * * * cd /path/to/project && docker compose -f docker-compose.prod.yml run --rm certbot renew && docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
   ```

## Резервное копирование БД

Скрипт `deploy/scripts/backup_db.sh` создаёт сжатый дамп `backups/coffee_shop_YYYYMMDD_HHMMSS.sql.gz` и автоматически удаляет архивы старше 14 дней:

```bash
chmod +x deploy/scripts/backup_db.sh
./deploy/scripts/backup_db.sh
```

Пример задания в `crontab` (ежедневно в 02:30):

```cron
30 2 * * * cd /path/to/project && ./deploy/scripts/backup_db.sh >> /var/log/coffee_backup.log 2>&1
```

Восстановление из бэкапа:

```bash
gunzip -c backups/coffee_shop_YYYYMMDD_HHMMSS.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```
