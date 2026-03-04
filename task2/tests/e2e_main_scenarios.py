import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

BASE_URL = os.environ["BASE_URL"]


def req(client, method, path, expected_status, token=None, body=None, expect_error=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, f"{BASE_URL}{path}", headers=headers, json=body)
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}

    request_id = response.headers.get("X-Request-Id")
    if not request_id:
        raise AssertionError(f"Missing X-Request-Id for {method} {path}")

    if response.status_code != expected_status:
        raise AssertionError(
            f"{method} {path}: expected {expected_status}, got {response.status_code}, payload={payload}"
        )
    if expect_error is not None and payload.get("error_code") != expect_error:
        raise AssertionError(f"{method} {path}: expected error {expect_error}, got {payload}")
    return payload


def register(client, email, role):
    return req(client, "POST", "/auth/register", 201, body={"email": email, "password": "StrongPass1", "role": role})


def login(client, email, password, status, error=None):
    return req(client, "POST", "/auth/login", status, body={"email": email, "password": password}, expect_error=error)


with httpx.Client(timeout=20) as c:
    req(c, "GET", "/health", 200)
    suffix = str(int(time.time() * 1000))

    # A. Auth
    seller_r = register(c, f"seller_{suffix}@example.com", "SELLER")
    user1_r = register(c, f"user1_{suffix}@example.com", "USER")
    user2_r = register(c, f"user2_{suffix}@example.com", "USER")
    admin_r = register(c, f"admin_{suffix}@example.com", "ADMIN")

    seller_token = seller_r["access_token"]
    user1_token = user1_r["access_token"]
    user2_token = user2_r["access_token"]
    admin_token = admin_r["access_token"]

    ok_login = login(c, f"user1_{suffix}@example.com", "StrongPass1", 200)
    if "access_token" not in ok_login:
        raise AssertionError("login success did not return access_token")
    login(c, f"user1_{suffix}@example.com", "WrongPass1", 401, error="TOKEN_INVALID")

    req(c, "POST", "/auth/refresh", 200, body={"refresh_token": ok_login["refresh_token"]})
    req(c, "POST", "/auth/refresh", 401, body={"refresh_token": "garbage"}, expect_error="REFRESH_TOKEN_INVALID")

    # B. Product access matrix
    req(
        c,
        "POST",
        "/products",
        403,
        token=user1_token,
        body={"name": "Blocked", "description": "No rights", "price": "10.00", "stock": 1, "category": "ELECTRONICS", "status": "ACTIVE"},
        expect_error="ACCESS_DENIED",
    )

    p1 = req(
        c,
        "POST",
        "/products",
        201,
        token=seller_token,
        body={"name": "Laptop", "description": "Main", "price": "100.00", "stock": 10, "category": "ELECTRONICS", "status": "ACTIVE"},
    )
    p1_id = p1["id"]

    req(
        c,
        "PUT",
        f"/products/{p1_id}",
        200,
        token=seller_token,
        body={"name": "Laptop Updated", "description": "Own update", "price": "110.00", "stock": 10, "category": "ELECTRONICS", "status": "ACTIVE"},
    )

    seller2_r = register(c, f"seller2_{suffix}@example.com", "SELLER")
    req(
        c,
        "PUT",
        f"/products/{p1_id}",
        403,
        token=seller2_r["access_token"],
        body={"name": "Hijack", "description": "Nope", "price": "111.00", "stock": 10, "category": "ELECTRONICS", "status": "ACTIVE"},
        expect_error="ACCESS_DENIED",
    )

    req(
        c,
        "PUT",
        f"/products/{p1_id}",
        200,
        token=admin_token,
        body={"name": "Admin Update", "description": "Admin", "price": "120.00", "stock": 8, "category": "ELECTRONICS", "status": "ACTIVE"},
    )

    archived = req(c, "DELETE", f"/products/{p1_id}", 200, token=seller_token)
    if archived["status"] != "ARCHIVED":
        raise AssertionError("soft delete failed")

    # C. Product list/filter/pagination
    p2 = req(
        c,
        "POST",
        "/products",
        201,
        token=seller_token,
        body={"name": "Mouse", "description": "M", "price": "15.00", "stock": 50, "category": "ELECTRONICS", "status": "ACTIVE"},
    )
    p3 = req(
        c,
        "POST",
        "/products",
        201,
        token=seller_token,
        body={"name": "Chair", "description": "C", "price": "70.00", "stock": 20, "category": "FURNITURE", "status": "ACTIVE"},
    )

    q1 = req(c, "GET", "/products?page=0&size=20", 200, token=user1_token)
    for key in ["items", "totalElements", "page", "size"]:
        if key not in q1:
            raise AssertionError(f"pagination response missing {key}")

    req(c, "GET", "/products?status=ACTIVE", 200, token=user1_token)
    q3 = req(c, "GET", "/products?category=ELECTRONICS", 200, token=user1_token)
    if any(item["category"] != "ELECTRONICS" for item in q3["items"]):
        raise AssertionError("category filter mismatch")

    # D. Validation contract
    bad_product = req(
        c,
        "POST",
        "/products",
        400,
        token=seller_token,
        body={"name": "", "description": None, "price": "0", "stock": -1, "category": "", "status": "ACTIVE"},
        expect_error="VALIDATION_ERROR",
    )
    if "violations" not in (bad_product.get("details") or {}):
        raise AssertionError("VALIDATION_ERROR details missing violations")

    req(c, "POST", "/orders", 400, token=user1_token, body={"items": []}, expect_error="VALIDATION_ERROR")
    req(
        c,
        "POST",
        "/orders",
        400,
        token=user1_token,
        body={"items": [{"product_id": p2["id"], "quantity": 0}]},
        expect_error="VALIDATION_ERROR",
    )
    req(
        c,
        "POST",
        "/orders",
        400,
        token=user1_token,
        body={"items": [{"product_id": p2["id"], "quantity": 1}], "promo_code": "bad-code"},
        expect_error="VALIDATION_ERROR",
    )

    # E. Promo code
    now = datetime.now(timezone.utc)
    req(
        c,
        "POST",
        "/promo-codes",
        201,
        token=seller_token,
        body={
            "code": "PROMO10",
            "discount_type": "PERCENTAGE",
            "discount_value": "10.00",
            "min_order_amount": "50.00",
            "max_uses": 2,
            "valid_from": (now - timedelta(hours=1)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
        },
    )

    req(
        c,
        "POST",
        "/promo-codes",
        201,
        token=admin_token,
        body={
            "code": "EXPIRED1",
            "discount_type": "FIXED_AMOUNT",
            "discount_value": "5.00",
            "min_order_amount": "1.00",
            "max_uses": 10,
            "valid_from": (now - timedelta(days=3)).isoformat(),
            "valid_until": (now - timedelta(days=1)).isoformat(),
        },
    )

    req(
        c,
        "POST",
        "/orders",
        422,
        token=user1_token,
        body={"items": [{"product_id": p2["id"], "quantity": 1}], "promo_code": "EXPIRED1"},
        expect_error="PROMO_CODE_INVALID",
    )

    req(
        c,
        "POST",
        "/promo-codes",
        201,
        token=seller_token,
        body={
            "code": "MIN200",
            "discount_type": "FIXED_AMOUNT",
            "discount_value": "5.00",
            "min_order_amount": "200.00",
            "max_uses": 10,
            "valid_from": (now - timedelta(hours=1)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
        },
    )
    req(
        c,
        "POST",
        "/orders",
        422,
        token=user1_token,
        body={"items": [{"product_id": p2["id"], "quantity": 1}], "promo_code": "MIN200"},
        expect_error="PROMO_CODE_MIN_AMOUNT",
    )

    # F. Order creation business rules
    req(
        c,
        "POST",
        "/orders",
        403,
        token=seller_token,
        body={"items": [{"product_id": p2["id"], "quantity": 1}]},
        expect_error="ACCESS_DENIED",
    )

    valid_order = req(
        c,
        "POST",
        "/orders",
        201,
        token=user1_token,
        body={"items": [{"product_id": p2["id"], "quantity": 4}], "promo_code": "PROMO10"},
    )

    req(
        c,
        "POST",
        "/orders",
        404,
        token=user2_token,
        body={"items": [{"product_id": str(uuid4()), "quantity": 1}]},
        expect_error="PRODUCT_NOT_FOUND",
    )

    inactive_product = req(
        c,
        "POST",
        "/products",
        201,
        token=seller_token,
        body={"name": "Inactive", "description": "I", "price": "9.00", "stock": 5, "category": "ELECTRONICS", "status": "INACTIVE"},
    )

    req(
        c,
        "POST",
        "/orders",
        409,
        token=user2_token,
        body={"items": [{"product_id": inactive_product["id"], "quantity": 1}]},
        expect_error="PRODUCT_INACTIVE",
    )

    low_stock = req(
        c,
        "POST",
        "/products",
        201,
        token=seller_token,
        body={"name": "LowStock", "description": "L", "price": "20.00", "stock": 1, "category": "ELECTRONICS", "status": "ACTIVE"},
    )

    stock_fail = req(
        c,
        "POST",
        "/orders",
        409,
        token=user2_token,
        body={"items": [{"product_id": low_stock["id"], "quantity": 5}]},
        expect_error="INSUFFICIENT_STOCK",
    )
    if "items" not in (stock_fail.get("details") or {}):
        raise AssertionError("INSUFFICIENT_STOCK missing details.items")

    req(
        c,
        "POST",
        "/orders",
        409,
        token=user1_token,
        body={"items": [{"product_id": p3["id"], "quantity": 1}]},
        expect_error="ORDER_HAS_ACTIVE",
    )

    # G. Order update/cancel/state machine
    req(
        c,
        "PUT",
        f"/orders/{valid_order['id']}",
        200,
        token=user1_token,
        body={"items": [{"product_id": p2["id"], "quantity": 1}]},
    )

    req(
        c,
        "PUT",
        f"/orders/{valid_order['id']}",
        403,
        token=user2_token,
        body={"items": [{"product_id": p2["id"], "quantity": 1}]},
        expect_error="ORDER_OWNERSHIP_VIOLATION",
    )

    req(c, "POST", f"/orders/{valid_order['id']}/status", 200, token=admin_token, body={"status": "PAYMENT_PENDING"})

    req(
        c,
        "PUT",
        f"/orders/{valid_order['id']}",
        409,
        token=user1_token,
        body={"items": [{"product_id": p2["id"], "quantity": 1}]},
        expect_error="INVALID_STATE_TRANSITION",
    )

    canceled = req(c, "POST", f"/orders/{valid_order['id']}/cancel", 200, token=user1_token)
    if canceled["status"] != "CANCELED":
        raise AssertionError("cancel failed from PAYMENT_PENDING")

    req(
        c,
        "POST",
        f"/orders/{valid_order['id']}/cancel",
        409,
        token=user1_token,
        expect_error="INVALID_STATE_TRANSITION",
    )

    o2 = req(c, "POST", "/orders", 201, token=user2_token, body={"items": [{"product_id": p2["id"], "quantity": 1}]})
    oid2 = o2["id"]
    req(c, "POST", f"/orders/{oid2}/status", 200, token=admin_token, body={"status": "PAYMENT_PENDING"})
    req(c, "POST", f"/orders/{oid2}/status", 200, token=admin_token, body={"status": "PAID"})
    req(c, "POST", f"/orders/{oid2}/status", 200, token=admin_token, body={"status": "SHIPPED"})
    req(c, "POST", f"/orders/{oid2}/status", 200, token=admin_token, body={"status": "COMPLETED"})
    req(
        c,
        "POST",
        f"/orders/{oid2}/status",
        409,
        token=admin_token,
        body={"status": "PAID"},
        expect_error="INVALID_STATE_TRANSITION",
    )

print("Main E2E scenarios A-H passed")
