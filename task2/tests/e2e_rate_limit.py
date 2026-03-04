import os
import time

import httpx

BASE_URL = os.environ["BASE_URL"]


def req(client, method, path, expected, token=None, body=None, err=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, f"{BASE_URL}{path}", headers=headers, json=body)
    payload = response.json()
    if response.status_code != expected:
        raise AssertionError(f"{method} {path} expected {expected}, got {response.status_code}, payload={payload}")
    if err and payload.get("error_code") != err:
        raise AssertionError(f"{method} {path} expected {err}, got {payload}")
    return payload


with httpx.Client(timeout=20) as c:
    suffix = str(int(time.time() * 1000))
    seller = req(
        c,
        "POST",
        "/auth/register",
        201,
        body={"email": f"rseller_{suffix}@example.com", "password": "StrongPass1", "role": "SELLER"},
    )
    user = req(
        c,
        "POST",
        "/auth/register",
        201,
        body={"email": f"ruser_{suffix}@example.com", "password": "StrongPass1", "role": "USER"},
    )

    seller_token = seller["access_token"]
    user_token = user["access_token"]

    product = req(
        c,
        "POST",
        "/products",
        201,
        token=seller_token,
        body={"name": "Rate", "description": "R", "price": "10.00", "stock": 20, "category": "ELECTRONICS", "status": "ACTIVE"},
    )

    order = req(c, "POST", "/orders", 201, token=user_token, body={"items": [{"product_id": product["id"], "quantity": 1}]})

    req(
        c,
        "POST",
        "/orders",
        429,
        token=user_token,
        body={"items": [{"product_id": product["id"], "quantity": 1}]},
        err="ORDER_LIMIT_EXCEEDED",
    )

    req(
        c,
        "PUT",
        f"/orders/{order['id']}",
        200,
        token=user_token,
        body={"items": [{"product_id": product["id"], "quantity": 2}]},
    )
    req(
        c,
        "PUT",
        f"/orders/{order['id']}",
        429,
        token=user_token,
        body={"items": [{"product_id": product["id"], "quantity": 1}]},
        err="ORDER_LIMIT_EXCEEDED",
    )

print("Rate limit checks passed")
