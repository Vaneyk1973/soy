import os
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./task2_test.db"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["ORDER_LIMIT_MINUTES"] = "0"

from app import Base, SessionLocal, app, engine  # noqa: E402


client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(email: str, password: str, role: str) -> str:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def create_product(token: str, name: str = "Laptop", stock: int = 5, price: str = "100.00") -> str:
    response = client.post(
        "/products",
        headers=auth_headers(token),
        json={
            "name": name,
            "description": "Desc",
            "price": price,
            "stock": stock,
            "category": "ELECTRONICS",
            "status": "ACTIVE",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_auth_and_roles():
    seller_token = register("seller@example.com", "StrongPass1", "SELLER")
    user_token = register("user@example.com", "StrongPass1", "USER")

    forbidden = client.post(
        "/products",
        headers=auth_headers(user_token),
        json={
            "name": "x",
            "description": None,
            "price": "10.00",
            "stock": 1,
            "category": "A",
            "status": "ACTIVE",
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "ACCESS_DENIED"

    product_id = create_product(seller_token)
    got = client.get(f"/products/{product_id}", headers=auth_headers(user_token))
    assert got.status_code == 200
    assert got.json()["id"] == product_id


def test_product_list_filter_pagination_and_soft_delete():
    seller_token = register("seller2@example.com", "StrongPass1", "SELLER")

    first_id = create_product(seller_token, name="Laptop", stock=10, price="200.00")
    create_product(seller_token, name="Mouse", stock=100, price="20.00")

    page = client.get(
        "/products?page=0&size=1&status=ACTIVE&category=ELECTRONICS",
        headers=auth_headers(seller_token),
    )
    assert page.status_code == 200
    body = page.json()
    assert body["page"] == 0
    assert body["size"] == 1
    assert body["totalElements"] == 2
    assert len(body["items"]) == 1

    archived = client.delete(f"/products/{first_id}", headers=auth_headers(seller_token))
    assert archived.status_code == 200
    assert archived.json()["status"] == "ARCHIVED"


def test_order_flow_with_promo_and_active_order_rule():
    seller_token = register("seller3@example.com", "StrongPass1", "SELLER")
    user_token = register("user3@example.com", "StrongPass1", "USER")

    product_id = create_product(seller_token, stock=5, price="100.00")
    now = datetime.now(timezone.utc)
    promo = client.post(
        "/promo-codes",
        headers=auth_headers(seller_token),
        json={
            "code": "PROMO10",
            "discount_type": "PERCENTAGE",
            "discount_value": "10.00",
            "min_order_amount": "50.00",
            "max_uses": 10,
            "valid_from": (now - timedelta(hours=1)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
        },
    )
    assert promo.status_code == 201, promo.text

    create = client.post(
        "/orders",
        headers=auth_headers(user_token),
        json={"items": [{"product_id": product_id, "quantity": 2}], "promo_code": "PROMO10"},
    )
    assert create.status_code == 201, create.text
    order = create.json()
    assert order["status"] == "CREATED"
    assert order["discount_amount"] == "20.00"
    assert order["total_amount"] == "180.00"

    second = client.post(
        "/orders",
        headers=auth_headers(user_token),
        json={"items": [{"product_id": product_id, "quantity": 1}]},
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "ORDER_HAS_ACTIVE"

    canceled = client.post(f"/orders/{order['id']}/cancel", headers=auth_headers(user_token))
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "CANCELED"


def test_validation_error_contract():
    seller_token = register("seller4@example.com", "StrongPass1", "SELLER")
    bad = client.post(
        "/products",
        headers=auth_headers(seller_token),
        json={
            "name": "",
            "description": None,
            "price": "0",
            "stock": -1,
            "category": "",
            "status": "ACTIVE",
        },
    )
    assert bad.status_code == 400
    body = bad.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "violations" in body["details"]
