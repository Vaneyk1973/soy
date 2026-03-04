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


with httpx.Client(timeout=20) as c:
    req(c, "GET", "/health", 200)
    suffix = str(int(time.time() * 1000))

    # 1) No token for protected endpoint.
    req(c, "GET", "/products", 401, expect_error="TOKEN_INVALID")

    # 2) Register duplicate email.
    email = f"dup_{suffix}@example.com"
    first = req(c, "POST", "/auth/register", 201, body={"email": email, "password": "StrongPass1", "role": "USER"})
    req(
        c,
        "POST",
        "/auth/register",
        400,
        body={"email": email, "password": "StrongPass1", "role": "USER"},
        expect_error="VALIDATION_ERROR",
    )

    # 3) Refresh token used as access token should be rejected.
    req(c, "GET", "/products", 401, token=first["refresh_token"], expect_error="TOKEN_INVALID")

    # 4) Setup actors and product for order/ownership/promo checks.
    seller = req(
        c,
        "POST",
        "/auth/register",
        201,
        body={"email": f"seller_extra_{suffix}@example.com", "password": "StrongPass1", "role": "SELLER"},
    )
    user1 = req(
        c,
        "POST",
        "/auth/register",
        201,
        body={"email": f"user1_extra_{suffix}@example.com", "password": "StrongPass1", "role": "USER"},
    )
    user2 = req(
        c,
        "POST",
        "/auth/register",
        201,
        body={"email": f"user2_extra_{suffix}@example.com", "password": "StrongPass1", "role": "USER"},
    )
    admin = req(
        c,
        "POST",
        "/auth/register",
        201,
        body={"email": f"admin_extra_{suffix}@example.com", "password": "StrongPass1", "role": "ADMIN"},
    )

    seller_token = seller["access_token"]
    user1_token = user1["access_token"]
    user2_token = user2["access_token"]
    admin_token = admin["access_token"]

    product = req(
        c,
        "POST",
        "/products",
        201,
        token=seller_token,
        body={"name": "PromoProduct", "description": "P", "price": "100.00", "stock": 10, "category": "ELECTRONICS", "status": "ACTIVE"},
    )

    # 5) Promo validation: wrong date range + duplicate code.
    now = datetime.now(timezone.utc)
    req(
        c,
        "POST",
        "/promo-codes",
        400,
        token=seller_token,
        body={
            "code": "BAD_RANGE",
            "discount_type": "PERCENTAGE",
            "discount_value": "10.00",
            "min_order_amount": "10.00",
            "max_uses": 1,
            "valid_from": (now + timedelta(days=1)).isoformat(),
            "valid_until": now.isoformat(),
        },
        expect_error="VALIDATION_ERROR",
    )

    promo = req(
        c,
        "POST",
        "/promo-codes",
        201,
        token=seller_token,
        body={
            "code": f"ONEUSE{suffix[-6:]}",
            "discount_type": "FIXED_AMOUNT",
            "discount_value": "15.00",
            "min_order_amount": "10.00",
            "max_uses": 1,
            "valid_from": (now - timedelta(minutes=5)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
        },
    )
    req(
        c,
        "POST",
        "/promo-codes",
        400,
        token=admin_token,
        body={
            "code": promo["code"],
            "discount_type": "FIXED_AMOUNT",
            "discount_value": "10.00",
            "min_order_amount": "1.00",
            "max_uses": 5,
            "valid_from": (now - timedelta(minutes=1)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
        },
        expect_error="VALIDATION_ERROR",
    )

    # 6) Promo usage and release on cancel (max_uses=1).
    order1 = req(
        c,
        "POST",
        "/orders",
        201,
        token=user1_token,
        body={"items": [{"product_id": product["id"], "quantity": 1}], "promo_code": promo["code"]},
    )
    if order1["discount_amount"] != "15.00" or order1["total_amount"] != "85.00":
        raise AssertionError(f"Unexpected discount math for fixed promo: {order1}")

    req(
        c,
        "POST",
        "/orders",
        422,
        token=user2_token,
        body={"items": [{"product_id": product["id"], "quantity": 1}], "promo_code": promo["code"]},
        expect_error="PROMO_CODE_INVALID",
    )

    req(c, "POST", f"/orders/{order1['id']}/cancel", 200, token=user1_token)

    order2 = req(
        c,
        "POST",
        "/orders",
        201,
        token=user2_token,
        body={"items": [{"product_id": product["id"], "quantity": 1}], "promo_code": promo["code"]},
    )
    if order2["discount_amount"] != "15.00":
        raise AssertionError(f"Promo usage was not released on cancel: {order2}")

    # 7) Ownership and role checks around order read.
    req(c, "GET", f"/orders/{order2['id']}", 403, token=user1_token, expect_error="ORDER_OWNERSHIP_VIOLATION")
    req(c, "GET", f"/orders/{order2['id']}", 403, token=seller_token, expect_error="ACCESS_DENIED")
    req(c, "GET", f"/orders/{order2['id']}", 200, token=admin_token)

    # 8) Not-found paths.
    unknown_order = str(uuid4())
    req(c, "GET", f"/orders/{unknown_order}", 404, token=admin_token, expect_error="ORDER_NOT_FOUND")
    req(
        c,
        "PUT",
        f"/orders/{unknown_order}",
        404,
        token=admin_token,
        body={"items": [{"product_id": product["id"], "quantity": 1}]},
        expect_error="ORDER_NOT_FOUND",
    )
    req(c, "POST", f"/orders/{unknown_order}/cancel", 404, token=admin_token, expect_error="ORDER_NOT_FOUND")
    req(
        c,
        "POST",
        f"/orders/{unknown_order}/status",
        404,
        token=admin_token,
        body={"status": "PAID"},
        expect_error="ORDER_NOT_FOUND",
    )

print("Additional E2E scenarios passed")
