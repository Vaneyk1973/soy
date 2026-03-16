import os

import pytest
from fastapi.testclient import TestClient
import grpc

os.environ.setdefault("GRPC_API_KEY", "test")
os.environ.setdefault("FLIGHT_GRPC_TARGET", "localhost:50051")
os.environ.setdefault("BOOKING_DATABASE_URL", "postgresql://booking:booking@localhost:5433/booking")

from booking_service.app.main import app
from booking_service.app.main import get_db as real_get_db


class DummyFlight:
    def __init__(self):
        self.id = "f1"
        self.flight_number = "SU123"
        self.airline = "SU"
        self.origin = "SVO"
        self.destination = "LED"
        self.departure_time = type("T", (), {"ToDatetime": lambda self: __import__("datetime").datetime(2026, 4, 1)})()
        self.arrival_time = type("T", (), {"ToDatetime": lambda self: __import__("datetime").datetime(2026, 4, 1, 2)})()
        self.total_seats = 100
        self.available_seats = 50
        self.price = 10000
        self.status = 1


class DummyFlightResponse:
    def __init__(self):
        self.flight = DummyFlight()


class DummySearchResponse:
    def __init__(self):
        self.flights = [DummyFlight()]


class DummyClient:
    def search_flights(self, origin, destination, date):
        return DummySearchResponse()

    def get_flight(self, flight_id):
        return DummyFlightResponse()

    def reserve_seats(self, flight_id, booking_id, seat_count):
        return None

    def release_reservation(self, booking_id):
        return None


class DummyRpcError(grpc.RpcError):
    def __init__(self, code, details="error"):
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


def _override_db():
    class DummySession:
        def add(self, *_args, **_kwargs):
            return None

        def commit(self):
            return None

        def refresh(self, *_args, **_kwargs):
            return None

    yield DummySession()


def _override_db_not_found():
    class DummySession:
        def get(self, *_args, **_kwargs):
            return None

    yield DummySession()


@pytest.mark.unit
def test_search_flights(monkeypatch):
    from booking_service.app import main
    main.flight_client = DummyClient()
    app.dependency_overrides[real_get_db] = _override_db
    client = TestClient(app)

    resp = client.get("/flights?origin=SVO&destination=LED&date=2026-04-01")
    assert resp.status_code == 200
    assert resp.json()[0]["origin"] == "SVO"
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_flight(monkeypatch):
    from booking_service.app import main
    main.flight_client = DummyClient()
    app.dependency_overrides[real_get_db] = _override_db
    client = TestClient(app)

    resp = client.get("/flights/f1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "f1"
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_search_missing_params(monkeypatch):
    from booking_service.app import main
    main.flight_client = DummyClient()
    app.dependency_overrides[real_get_db] = _override_db
    client = TestClient(app)

    resp = client.get("/flights?origin=SVO")
    assert resp.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_invalid_date(monkeypatch):
    from booking_service.app import main
    main.flight_client = DummyClient()
    app.dependency_overrides[real_get_db] = _override_db
    client = TestClient(app)

    resp = client.get("/flights?origin=SVO&destination=LED&date=bad-date")
    assert resp.status_code == 400
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_flight_not_found(monkeypatch):
    from booking_service.app import main

    class NotFoundClient(DummyClient):
        def get_flight(self, flight_id):
            raise DummyRpcError(grpc.StatusCode.NOT_FOUND, "not found")

    main.flight_client = NotFoundClient()
    app.dependency_overrides[real_get_db] = _override_db
    client = TestClient(app)

    resp = client.get("/flights/missing")
    assert resp.status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_circuit_breaker_open(monkeypatch):
    from booking_service.app import main

    class BreakerClient(DummyClient):
        def search_flights(self, origin, destination, date):
            from booking_service.app.circuit_breaker import CircuitBreakerOpen
            raise CircuitBreakerOpen("open")

    main.flight_client = BreakerClient()
    app.dependency_overrides[real_get_db] = _override_db
    client = TestClient(app)

    resp = client.get("/flights?origin=SVO&destination=LED")
    assert resp.status_code == 503
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_create_booking_insufficient_seats(monkeypatch):
    from booking_service.app import main

    class ExhaustedClient(DummyClient):
        def reserve_seats(self, flight_id, booking_id, seat_count):
            raise DummyRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED, "not enough seats")

    main.flight_client = ExhaustedClient()
    app.dependency_overrides[real_get_db] = _override_db
    client = TestClient(app)

    payload = {
        "user_id": "u1",
        "flight_id": "f1",
        "passenger_name": "Alice",
        "passenger_email": "alice@example.com",
        "seat_count": 2,
    }
    resp = client.post("/bookings", json=payload)
    assert resp.status_code == 409
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_create_booking_flight_not_found(monkeypatch):
    from booking_service.app import main

    class NotFoundClient(DummyClient):
        def get_flight(self, flight_id):
            raise DummyRpcError(grpc.StatusCode.NOT_FOUND, "not found")

    main.flight_client = NotFoundClient()
    app.dependency_overrides[real_get_db] = _override_db
    client = TestClient(app)

    payload = {
        "user_id": "u1",
        "flight_id": "f1",
        "passenger_name": "Alice",
        "passenger_email": "alice@example.com",
        "seat_count": 1,
    }
    resp = client.post("/bookings", json=payload)
    assert resp.status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_create_booking_invalid_payload(monkeypatch):
    from booking_service.app import main
    main.flight_client = DummyClient()
    app.dependency_overrides[real_get_db] = _override_db
    client = TestClient(app)

    payload = {
        "user_id": "u1",
        "flight_id": "f1",
        "passenger_name": "Alice",
        "passenger_email": "alice@example.com",
        "seat_count": 0,
    }
    resp = client.post("/bookings", json=payload)
    assert resp.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_booking_not_found(monkeypatch):
    app.dependency_overrides[real_get_db] = _override_db_not_found
    client = TestClient(app)

    resp = client.get("/bookings/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_cancel_booking_not_found(monkeypatch):
    app.dependency_overrides[real_get_db] = _override_db_not_found
    client = TestClient(app)

    resp = client.post("/bookings/00000000-0000-0000-0000-000000000000/cancel")
    assert resp.status_code == 404
    app.dependency_overrides.clear()
