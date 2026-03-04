# Task 2: Marketplace API

FastAPI-сервис маркетплейса с:
- CRUD для пользователей, товаров, заказов и промокодов
- ролевой моделью (`ADMIN`, `SELLER`, `USER`)
- JWT-аутентификацией (access + refresh)
- бизнес-ограничениями по заказам и состояниям
- логированием запросов с `X-Request-Id` и маскированием чувствительных данных
- тестами уровня unit/integration + e2e-сценариями

## Что реализовано
- Аутентификация и авторизация:
  - `POST /auth/register`
  - `POST /auth/login`
  - `POST /auth/refresh`
- Товары:
  - создание/редактирование/архивация (ролевая проверка владельца/админа)
  - фильтрация, пагинация, доступ к списку и карточке
- Промокоды:
  - валидация периода действия, лимита использований, минимальной суммы
  - поддержка `PERCENTAGE` и `FIXED_AMOUNT`
- Заказы:
  - создание/обновление/отмена
  - state-machine переходы статусов
  - запрет второго активного заказа для пользователя
  - ограничение частоты операций (`ORDER_LIMIT_MINUTES`)
- Ошибки и контракт:
  - единый формат `ErrorResponse` (`error_code`, `message`, `details`)
  - валидационные ошибки возвращаются как `VALIDATION_ERROR`

## Технологии
- Python 3.10+
- FastAPI
- SQLAlchemy 2.x
- PostgreSQL (Docker-режим) / SQLite (тестовый режим)
- Flyway для миграций
- `datamodel-code-generator` для генерации моделей из OpenAPI
- pytest + httpx

## Структура проекта
- API: `task2/app.py`
- OpenAPI-спецификация: `task2/src/main/resources/openapi/openapi.yaml`
- Генерация моделей: `task2/scripts/generate_openapi_code.sh`
- Сгенерированные модели: `task2/generated/openapi_models.py`
- SQL-миграции: `task2/db/migration/V1__init.sql`
- Тесты:
  - `task2/tests/test_api.py`
  - `task2/tests/e2e_main_scenarios.py`
  - `task2/tests/e2e_additional_scenarios.py`
  - `task2/tests/check_logs_and_db_proof.py`
  - `task2/tests/e2e_rate_limit.py`
  - `task2/tests/run_all_tests.sh`

## Переменные окружения
- `DATABASE_URL`
  - по умолчанию: `postgresql+psycopg://postgres:postgres@localhost:5432/marketplace`
- `JWT_SECRET`
  - по умолчанию: `dev-secret`
- `ACCESS_TOKEN_MINUTES`
  - по умолчанию: `20`
- `REFRESH_TOKEN_DAYS`
  - по умолчанию: `14`
- `ORDER_LIMIT_MINUTES`
  - по умолчанию: `5`

## Быстрый старт (Docker)
```bash
cd task2
docker compose up --build
```

Поднимаются сервисы:
- `postgres`
- `flyway`
- `api`

Проверка:
```bash
curl -i http://localhost:8000/health
```

Swagger UI:
```text
http://localhost:8000/docs
```

## Локальный запуск (без Docker)
```bash
cd task2
python3 -m venv ../.venv
source ../.venv/bin/activate
pip install -r requirements.txt
./scripts/generate_openapi_code.sh
uvicorn app:app --host 0.0.0.0 --port 8000
```

Проверка:
```bash
curl -i http://127.0.0.1:8000/health
```

## Как работают тесты
Тесты разделены на 2 слоя.

1. `pytest` (`tests/test_api.py`)
- Проверяет ключевую доменную логику через `FastAPI TestClient`
- Работает на SQLite (`task2_test.db`) без поднятия отдельного сервера
- Быстрый smoke/contract набор

2. Полный e2e runner (`tests/run_all_tests.sh`)
- Поднимает реальный `uvicorn`
- Перед запуском генерирует модели из OpenAPI
- Создает чистую SQLite-базу для каждого этапа
- Выполняет:
  - `[1/5]` `pytest -q`
  - `[2/5]` `tests/e2e_main_scenarios.py` (сквозные сценарии A-H)
  - `[3/5]` `tests/e2e_additional_scenarios.py` (дополнительные edge cases)
  - `[4/5]` `tests/check_logs_and_db_proof.py` (JSON-логи + SQL proof)
  - `[5/5]` `tests/e2e_rate_limit.py` (ошибки `ORDER_LIMIT_EXCEEDED`)

## Запуск тестов
Минимальный запуск:
```bash
cd task2
source ../.venv/bin/activate
python -m pytest -q
```

Полный прогон:
```bash
cd task2
bash tests/run_all_tests.sh
```

Полезные переменные для e2e:
- `HOST` (по умолчанию `127.0.0.1`)
- `PORT` (по умолчанию `18000`)
- `BASE_URL` (по умолчанию `http://$HOST:$PORT`)
- `HEALTH_TIMEOUT_SECONDS` (по умолчанию `25`)

Пример:
```bash
cd task2
HOST=127.0.0.1 PORT=19000 bash tests/run_all_tests.sh
```

## Что проверяется e2e-сценариями
- Auth: регистрация, логин, refresh, ошибки токенов
- Матрица прав на товары: `USER`/`SELLER`/`ADMIN`
- Фильтрация и пагинация товаров
- Контракт валидационных ошибок (`VALIDATION_ERROR`)
- Промокоды: срок действия, min amount, invalid code
- Заказы: создание, ownership, transitions, cancel
- Ограничение частоты операций по заказам
- Наличие `X-Request-Id` и структура JSON-логов
- Маскирование полей `password/secret/pass` в логах
