# NFC-таблички отзывов

Один Flask-сервис для любого количества бизнесов. NFC-метка содержит постоянный URL `/r/<id>`, а ссылки на Яндекс Карты и 2ГИС меняются через админку. HTML/CSS без внешних шрифтов, JavaScript и сторонних запросов.

## Локальный запуск (Python 3.12)

```sh
git clone https://github.com/5sz7twtzkh-boop/review-nfc.git
cd review-nfc
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell вместо предыдущей команды:
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Скопируйте `.env.example` в `.env`. Заполните:

```dotenv
APP_ENV=development
SECRET_KEY=вставьте-случайную-строку-не-короче-32-символов
ADMIN_PASSWORD=вставьте-свой-пароль-не-короче-12-символов
```

Создать случайный SECRET_KEY: `python -c "import secrets; print(secrets.token_hex(32))"`.
Значения выше — пояснения, выберите собственные секреты. `.env` исключён из Git.

```sh
python app.py
```

- Публичная страница: http://127.0.0.1:5000/r/001
- Админка: http://127.0.0.1:5000/admin/login
- Проверка: http://127.0.0.1:5000/health

База автоматически создаётся в `instance/reviews.db`. При первом запуске создаётся `001 / Демо-компания` со ссылками `https://yandex.ru/maps/` и `https://2gis.ru/`. Удаление демо-записи сохраняется после перезапуска. `/` перенаправляет на `/r/001`, поэтому после её удаления корневая ссылка также приведёт к 404.

## Деплой на Render пошагово

1. Откройте [Render Dashboard](https://dashboard.render.com/) и подключите GitHub.
2. Выберите **New → Blueprint**, затем репозиторий `5sz7twtzkh-boop/review-nfc`, ветку `main`.
3. Render прочитает `render.yaml`: Python 3.12 через `.python-version`, сборка `pip install -r requirements.txt`, запуск `gunicorn app:app`, health check `/health`.
4. Введите `ADMIN_PASSWORD` (минимум 12 символов). `SECRET_KEY` Render сгенерирует автоматически. `APP_ENV=production` уже задан.
5. Примените Blueprint и дождитесь статуса **Live**. Бесплатный тариф в Blueprint предназначен для теста.
6. Откройте адрес сервиса из Dashboard: `https://<ваш-сервис>.onrender.com/health`, затем `/r/001`.
7. Войдите на `https://<ваш-сервис>.onrender.com/admin/login` с заданным паролем. Измените демо-бизнес или создайте ID `002`.
8. Для постоянного использования подключите PostgreSQL по инструкции ниже и при необходимости свой домен в Settings → Custom Domains. До массовой записи NFC выберите постоянный домен.

Альтернатива Blueprint: **New → Web Service**, тот же репозиторий и команды сборки/запуска, `/health`, Python 3.12 и переменные ниже.

Поля Blueprint сверены с [документацией Render](https://render.com/docs/blueprint-spec); выбор Python описан [здесь](https://render.com/docs/python-version).

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `SECRET_KEY` | Обязательная случайная строка от 32 символов, подпись сессий и CSRF; Render генерирует её |
| `ADMIN_PASSWORD` | Обязательный пароль админки от 12 символов, без значения по умолчанию |
| `APP_ENV` | `production` по умолчанию; только для локального HTTP используйте `development` |
| `DATABASE_URL` | Необязательно для теста: SQLite по умолчанию; для production — URL PostgreSQL |
| `PORT` | Render задаёт автоматически; Gunicorn использует 8000 по умолчанию |

Production использует защищённые HttpOnly/SameSite cookies с флагом Secure. Поэтому production-админка требует HTTPS. Debug отключён. При смене пароля старые админ-сессии перестают действовать. Сессия живёт 8 часов, выход выполняется POST с CSRF.

## Хранение данных: важно для production

**SQLite на бесплатном Render — только для теста. Для production нужно PostgreSQL.** Файловая система Render эфемерна: база SQLite теряется при перезапуске, новом деплое или засыпании. Бесплатный web-сервис засыпает после простоя, поэтому первое открытие может задерживаться. [Ограничения бесплатного Render](https://render.com/docs/free).

1. Создайте постоянную PostgreSQL-базу (Render → New → Postgres, в регионе web-сервиса). Выберите тариф с нужным сроком хранения и резервными копиями: бесплатная Render Postgres не предназначена для бессрочного production.
2. Скопируйте Internal Database URL в переменную web-сервиса `DATABASE_URL`.
3. Сохраните переменные и перезапустите сервис. Поддерживаются URL `postgres://`, `postgresql://` и `postgresql+psycopg://`. Драйвер уже установлен, менять код не нужно.
4. Проверьте `/health`, публичную страницу и вход; создайте бизнесы в новой базе.

Переключение DATABASE_URL создаёт таблицы в новой базе, но **не переносит старые записи**. Подключайте PostgreSQL до ввода реальных табличек. Для переноса имеющихся данных сохраните SQLite, остановите запись, перенесите таблицу `plates` подходящим инструментом и проверьте все ID перед переключением. Не меняйте ID при переносе. Настройте резервное копирование PostgreSQL и проверяйте восстановление.

Модель SQLAlchemy отделена от маршрутов на уровне ORM; запросы совместимы с SQLite/PostgreSQL. `create_all()` создаёт отсутствующие таблицы, но не мигрирует изменение схемы — для последующих изменений схемы нужны миграции (например Alembic). Gunicorn предварительно инициализирует приложение до запуска worker; соединения сбрасываются после fork. Для тестовой SQLite оставлен один worker.

## Как пользоваться NFC

Запишите в NFC-метку **запись URL / URI (NDEF)**:

```text
https://<ваш-домен>/r/001
```

Для следующего бизнеса создайте в админке ID `002`, название и две ссылки, включите табличку и запишите `https://<ваш-домен>/r/002` в другую метку. Ссылки карт можно менять без перезаписи NFC. Изменение ID или домена потребует перезаписи метки. Новые сайты не нужны.

Выключенная или отсутствующая табличка возвращает 404. Если одна ссылка пустая, посетитель увидит «Ссылка пока не добавлена», а вторая кнопка продолжит работать. Удаление требует страницы подтверждения и POST; GET ничего не удаляет.

## Проверки и production-запуск

```sh
python -m compileall -q app.py nfc tests scripts gunicorn.conf.py
python -m unittest discover -s tests -v
# Linux/macOS:
python scripts/smoke_gunicorn.py
gunicorn app:app
```

Gunicorn работает на Unix, на Windows используйте `python app.py` для разработки или Docker для production. GitHub Actions запускает тесты и настоящий Gunicorn на Ubuntu, проверяя `/`, `/r/001`, `/health`, `/admin/login` через HTTP.

```sh
docker build -t review-nfc .
docker run --rm -p 8000:8000 --env-file .env -e APP_ENV=development review-nfc
```

Для Docker в production задайте `APP_ENV=production`, PostgreSQL и HTTPS reverse proxy; контейнер запускается от непривилегированного пользователя. Локальная команда выше использует HTTP только для проверки.

Все изменяющие формы защищены CSRF. Ссылки проверяются на http/https, hostname и длину; HTML экранируется. Ограничение входа — 10 попыток за 15 минут на адрес прямого соединения, сохраняется в БД. За proxy несколько посетителей могут разделять лимит; заголовок X-Forwarded-For намеренно не считается доверенным. Для высоких нагрузок добавьте ограничение на уровне проверенного edge/proxy. `/health` проверяет доступность процесса, не соединение с базой.

## Файлы

- `app.py` — точка входа, загрузка `.env`.
- `nfc/__init__.py` — фабрика Flask, SQLAlchemy, маршруты, сессии, валидация.
- `nfc/templates/` — публичная страница, админка, формы и страницы ошибок.
- `nfc/static/style.css` — адаптивный интерфейс.
- `requirements.txt`, `.python-version` — зависимости и Python.
- `render.yaml`, `Dockerfile`, `gunicorn.conf.py` — production.
- `tests/test_app.py`, `scripts/smoke_gunicorn.py`, `.github/workflows/tests.yml` — проверки.
- `.env.example`, `.gitignore`, `.dockerignore` — локальная конфигурация и исключения.
