# Task 3 - Flight Booking

## Run

```bash
cd task3
docker-compose up --build
```

## Services

- Booking Service (REST): `http://localhost:8000`
- Flight Service (gRPC): `localhost:50051`
- PostgreSQL: `localhost:5433` (booking), `localhost:5434` (flight)
- Redis Sentinel: `localhost:26379`

## Описание работы системы

Система состоит из двух микросервисов и двух изолированных БД:

- **Booking Service** — REST API для клиентов. Хранит бронирования в своей PostgreSQL.
- **Flight Service** — gRPC сервис для управления рейсами и местами. Хранит рейсы в своей PostgreSQL и использует Redis для кеширования.

Взаимодействие:

```
Client (REST) → Booking Service → (gRPC) → Flight Service
                         ↓                    ↓
                    PostgreSQL           PostgreSQL + Redis
```

### Основные сценарии

**Поиск рейсов**

`GET /flights?origin=...&destination=...&date=...`  
Booking Service проксирует запрос в Flight Service (SearchFlights). Возвращаются рейсы только со статусом `SCHEDULED`.

**Получение рейса**

`GET /flights/{id}`  
Booking Service вызывает Flight Service (GetFlight). Если рейс не найден — 404.

**Создание бронирования**

`POST /bookings` с `user_id`, `flight_id`, `passenger_name`, `passenger_email`, `seat_count`:

1. Booking Service вызывает `GetFlight`, чтобы получить цену и проверить наличие рейса.
2. Затем вызывает `ReserveSeats` — места резервируются атомарно в Flight Service (с блокировкой `SELECT FOR UPDATE`).
3. Цена фиксируется на момент бронирования: `total_price = seat_count * flight.price`.
4. Создаётся запись бронирования со статусом `CONFIRMED`.
5. Если резервирование не удалось — бронирование не создаётся.

**Отмена бронирования**

`POST /bookings/{id}/cancel`:

1. Проверяется, что бронирование в статусе `CONFIRMED`.
2. Вызывается `ReleaseReservation` в Flight Service — места возвращаются, статус резервации обновляется.
3. Статус бронирования становится `CANCELLED`.

### Flight Service (gRPC)

Контракт определён в `proto/flight.proto`. Ключевые методы:

- `SearchFlights` — поиск рейсов по маршруту и дате.
- `GetFlight` — получение рейса по ID.
- `ReserveSeats` — атомарное резервирование мест.
- `ReleaseReservation` — отмена резервации и возврат мест.
- `UpdateFlight` — изменение статуса/цены рейса (и инвалидация кеша).

### Транзакции и целостность

- В Flight Service резервирование и отмена выполняются в одной транзакции.
- Используется `SELECT FOR UPDATE` для предотвращения гонок при бронировании последних мест.
- В Booking Service бронирование создаётся только после успешного `ReserveSeats`.
- В БД настроены ограничения целостности (положительные цены, места не отрицательные и т.д.).

### Аутентификация межсервисных вызовов

Booking Service передаёт API ключ в gRPC metadata (`x-api-key`).  
Flight Service проверяет ключ для всех методов. При отсутствии/ошибке — `UNAUTHENTICATED`.

### Кеширование (Redis)

Flight Service использует Cache-Aside:

1. Проверка кеша → при промахе запрос к БД → запись в кеш с TTL.
2. Ключи:
   - `flight:{id}` — информация о рейсе
   - `search:{origin}:{destination}:{date}` — результаты поиска
3. TTL по умолчанию 5 минут.
4. Кеш инвалидируется при изменениях (`ReserveSeats`, `ReleaseReservation`, `UpdateFlight`).

### Отказоустойчивость

- **Retry** в Booking Service: до 3 попыток с экспоненциальной задержкой (100/200/400ms) только для `UNAVAILABLE` и `DEADLINE_EXCEEDED`.
- **Идемпотентность** `ReserveSeats`: повторный вызов с тем же `booking_id` не создаёт дубликат.
- **Circuit Breaker** реализован как gRPC interceptor. Параметры настраиваются через переменные окружения.
- **Redis Sentinel** обеспечивает отказоустойчивость мастер-ноды.

## REST API

- `GET /flights?origin=SVO&destination=LED&date=2026-04-01`
- `GET /flights/{id}`
- `POST /bookings`
- `GET /bookings/{id}`
- `POST /bookings/{id}/cancel`
- `GET /bookings?user_id=X`

## Тесты

Полная схема тестовой архитектуры: [tests/ARCHITECTURE.md](/home/user/soy/task3/tests/ARCHITECTURE.md).

### Как устроены тесты и взаимодействие модулей

Тесты разделены на три уровня: unit, integration и e2e. Каждый уровень проверяет разные границы системы и по‑разному взаимодействует с модулями.

**Unit tests (без внешних сервисов):**

- `tests/unit/test_cache.py` — проверяет Cache‑Aside логику в `flight_service.app.cache`:
  - cache hit/miss, TTL, удаление по шаблону.
- `tests/unit/test_auth_interceptor.py` — проверяет `AuthInterceptor`:
  - отклонение при неверном API key, пропуск при верном.
- `tests/unit/test_circuit_breaker.py` — проверяет конечный автомат circuit breaker:
  - переходы `CLOSED → OPEN → HALF_OPEN → CLOSED`.
- `tests/unit/test_grpc_client_retry.py` — проверяет retry/backoff в `booking_service.app.grpc_client`:
  - повтор только на `UNAVAILABLE/DEADLINE_EXCEEDED`, корректные интервалы.
- `tests/unit/test_booking_handlers.py` — проверяет REST‑хендлеры Booking Service:
  - валидацию входных данных, корректные HTTP коды,
  - маппинг gRPC ошибок в REST ответы,
  - поведение при open circuit.

**Integration tests (нужен docker-compose up):**

- `tests/integration/test_flight_grpc.py` — реальные gRPC вызовы в Flight Service:
  - Search/Get/Reserve/Release,
  - идемпотентность `ReserveSeats`,
  - UpdateFlight и инвалидация кеша,
  - отбрасывание не‑`SCHEDULED` рейсов в поиске,
  - ошибки `NOT_FOUND`, `INVALID_ARGUMENT`, `RESOURCE_EXHAUSTED`,
  - проверка отказа без аутентификации.
- `tests/integration/test_db_constraints.py` — проверяет ограничения БД:
  - положительные значения мест/цен,
  - уникальность `flight_number + departure_date`,
  - запрет `seat_count <= 0`.

**E2E tests (нужен docker-compose up):**

- `tests/e2e/test_booking_flow.py` — полный путь REST → gRPC → DB → Redis:
  - поиск рейсов, создание бронирования, отмена,
  - повторная отмена (409),
  - недостаток мест (409),
  - отсутствие рейса/бронирования (404),
  - ошибки валидации (422/400).

### Как связаны модули

- **REST слой** (`booking_service.app.main`) — принимает запросы и вызывает **gRPC клиент** (`booking_service.app.grpc_client`).
- **gRPC клиент** использует:
  - retry/backoff,
  - circuit breaker как interceptor,
  - API key в metadata.
- **Flight Service** (`flight_service.app.grpc_server`) работает с БД через SQLAlchemy и кеширует данные в Redis (Cache‑Aside).
- **Redis** используется только в Flight Service, все мутации инвалидируют кеш.

### Запуск тестов

Установка зависимостей для тестов:

```bash
pip install -r requirements.txt
```

Запуск всех тестов:

```bash
./run_tests.sh
```

Прямой запуск через pytest (все тесты):

```bash
pytest
```
