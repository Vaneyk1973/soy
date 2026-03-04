# E2E Scenarios

This file describes all E2E scenarios executed by `tests/run_all_tests.sh`.

## Execution Flow

`run_all_tests.sh` runs E2E in this order:
1. `tests/e2e_main_scenarios.py`
2. `tests/e2e_additional_scenarios.py`
3. `tests/check_logs_and_db_proof.py`
4. `tests/e2e_rate_limit.py` (on a fresh DB with `ORDER_LIMIT_MINUTES=5`)

All HTTP checks also verify presence of `X-Request-Id` header.

## Main E2E (`tests/e2e_main_scenarios.py`)

### A. Auth
1. Register `SELLER`, `USER`, `USER`, `ADMIN`.
2. Login with valid credentials returns token pair.
3. Login with invalid password returns `401 TOKEN_INVALID`.
4. Refresh with valid refresh token returns new token pair.
5. Refresh with invalid token returns `401 REFRESH_TOKEN_INVALID`.

### B. Product access matrix
1. `USER` cannot create product: `403 ACCESS_DENIED`.
2. `SELLER` can create product.
3. Product owner (`SELLER`) can update product.
4. Another seller cannot update a product they do not own: `403 ACCESS_DENIED`.
5. `ADMIN` can update product.
6. `SELLER` soft-deletes product, status becomes `ARCHIVED`.

### C. Product listing/filter/pagination
1. Create active products in multiple categories.
2. Verify paginated response contains `items`, `totalElements`, `page`, `size`.
3. Verify `status=ACTIVE` filter works.
4. Verify `category=ELECTRONICS` returns only matching category.

### D. Validation contract
1. Invalid product payload returns `400 VALIDATION_ERROR`.
2. `details.violations` is present for validation errors.
3. Invalid order payloads return `400 VALIDATION_ERROR`:
   - empty items
   - quantity `0`
   - invalid promo format

### E. Promo code
1. Create valid active promo (`PROMO10`).
2. Create expired promo (`EXPIRED1`).
3. Using expired promo returns `422 PROMO_CODE_INVALID`.
4. Create promo with high min amount (`MIN200`).
5. Using promo below min order total returns `422 PROMO_CODE_MIN_AMOUNT`.

### F. Order creation business rules
1. `SELLER` cannot create order: `403 ACCESS_DENIED`.
2. Valid order creation by `USER` succeeds.
3. Unknown product in order returns `404 PRODUCT_NOT_FOUND`.
4. Inactive product returns `409 PRODUCT_INACTIVE`.
5. Insufficient stock returns `409 INSUFFICIENT_STOCK` with `details.items`.
6. Second active order for same user returns `409 ORDER_HAS_ACTIVE`.

### G. Order update/cancel/state machine
1. Owner can update order while status is `CREATED`.
2. Another user cannot update an order they do not own: `403 ORDER_OWNERSHIP_VIOLATION`.
3. `ADMIN` changes status to `PAYMENT_PENDING`.
4. Update after non-`CREATED` status returns `409 INVALID_STATE_TRANSITION`.
5. Cancel from `PAYMENT_PENDING` succeeds, status becomes `CANCELED`.
6. Re-cancel canceled order returns `409 INVALID_STATE_TRANSITION`.
7. Valid transition chain works:
   - `CREATED -> PAYMENT_PENDING -> PAID -> SHIPPED -> COMPLETED`
8. Invalid backward transition returns `409 INVALID_STATE_TRANSITION`.

## Additional E2E (`tests/e2e_additional_scenarios.py`)

### 1. Auth and token edge cases
1. Protected endpoint without token returns `401 TOKEN_INVALID`.
2. Duplicate email registration returns `400 VALIDATION_ERROR`.
3. Using refresh token as bearer access token returns `401 TOKEN_INVALID`.

### 2. Promo validation edge cases
1. Promo with `valid_until <= valid_from` returns `400 VALIDATION_ERROR`.
2. Duplicate promo code returns `400 VALIDATION_ERROR`.

### 3. Promo lifecycle and discount math
1. Create promo with `max_uses=1` and fixed discount.
2. First order with promo succeeds and validates totals:
   - `discount_amount = 15.00`
   - `total_amount = 85.00`
3. Second order with same promo (while used) returns `422 PROMO_CODE_INVALID`.
4. Cancel first order releases promo usage.
5. Another user can reuse promo successfully after cancel.

### 4. Order ownership and role checks
1. Non-owner `USER` cannot read order: `403 ORDER_OWNERSHIP_VIOLATION`.
2. `SELLER` cannot read user order: `403 ACCESS_DENIED`.
3. `ADMIN` can read any order.

### 5. ORDER_NOT_FOUND matrix
For random order ID, all return `404 ORDER_NOT_FOUND`:
1. `GET /orders/{id}`
2. `PUT /orders/{id}`
3. `POST /orders/{id}/cancel`
4. `POST /orders/{id}/status`

## Logging + DB proof (`tests/check_logs_and_db_proof.py`)

### H. Logs
1. Uvicorn/app log file exists.
2. JSON access logs are present.
3. Required fields exist in log records:
   - `request_id`, `method`, `endpoint`, `status_code`, `duration_ms`, `user_id`, `timestamp`
4. `request_body` is logged for mutating requests.
5. Sensitive fields are masked (`password` becomes `***`).

### I. DB proof
Prints recent rows from:
1. `users`
2. `products`
3. `orders`
4. `order_items`
5. `promo_codes`
6. `user_operations`

## Rate-limit E2E (`tests/e2e_rate_limit.py`)

Runs on separate DB with `ORDER_LIMIT_MINUTES=5`.

1. First order creation succeeds.
2. Immediate second create returns `429 ORDER_LIMIT_EXCEEDED`.
3. First update succeeds.
4. Immediate second update returns `429 ORDER_LIMIT_EXCEEDED`.

## How to Run

From repository root:

```bash
cd task2
bash tests/run_all_tests.sh
```
