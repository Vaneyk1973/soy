import uuid
from datetime import datetime, timezone, date

import psycopg2
import pytest
import requests


def _insert_flight(flight_db_dsn, flight_id, dep_time, arr_time, total_seats, available_seats, price):
    with psycopg2.connect(flight_db_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO flights (id, flight_number, airline, origin, destination, departure_time, departure_date,
                                    arrival_time, total_seats, available_seats, price, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    str(flight_id),
                    "SU124",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    total_seats,
                    available_seats,
                    price,
                    "SCHEDULED",
                ),
            )
        conn.commit()


@pytest.mark.e2e
def test_booking_lifecycle(clean_dbs, flight_db_dsn):
    flight_id = uuid.uuid4()
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

    _insert_flight(flight_db_dsn, flight_id, dep_time, arr_time, 50, 50, 20000.00)

    base_url = "http://localhost:8000"

    flights = requests.get(
        f"{base_url}/flights",
        params={"origin": "SVO", "destination": "LED", "date": "2026-04-01"},
        timeout=5,
    )
    assert flights.status_code == 200
    assert len(flights.json()) == 1

    payload = {
        "user_id": "u1",
        "flight_id": str(flight_id),
        "passenger_name": "Alice",
        "passenger_email": "alice@example.com",
        "seat_count": 2,
    }
    booking = requests.post(f"{base_url}/bookings", json=payload, timeout=5)
    assert booking.status_code == 201
    booking_id = booking.json()["id"]

    booking_get = requests.get(f"{base_url}/bookings/{booking_id}", timeout=5)
    assert booking_get.status_code == 200
    assert booking_get.json()["status"] == "CONFIRMED"

    booking_list = requests.get(f"{base_url}/bookings", params={"user_id": "u1"}, timeout=5)
    assert booking_list.status_code == 200
    assert len(booking_list.json()["items"]) == 1

    cancelled = requests.post(f"{base_url}/bookings/{booking_id}/cancel", timeout=5)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    cancelled_again = requests.post(f"{base_url}/bookings/{booking_id}/cancel", timeout=5)
    assert cancelled_again.status_code == 409


@pytest.mark.e2e
def test_booking_insufficient_seats(clean_dbs, flight_db_dsn):
    flight_id = uuid.uuid4()
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    _insert_flight(flight_db_dsn, flight_id, dep_time, arr_time, 1, 1, 12000.00)

    base_url = "http://localhost:8000"
    payload = {
        "user_id": "u2",
        "flight_id": str(flight_id),
        "passenger_name": "Bob",
        "passenger_email": "bob@example.com",
        "seat_count": 2,
    }
    booking = requests.post(f"{base_url}/bookings", json=payload, timeout=5)
    assert booking.status_code == 409

    booking_list = requests.get(f"{base_url}/bookings", params={"user_id": "u2"}, timeout=5)
    assert booking_list.status_code == 200
    assert booking_list.json()["items"] == []


@pytest.mark.e2e
def test_booking_not_found():
    base_url = "http://localhost:8000"
    missing = requests.get(f"{base_url}/bookings/{uuid.uuid4()}", timeout=5)
    assert missing.status_code == 404


@pytest.mark.e2e
def test_invalid_date_query():
    base_url = "http://localhost:8000"
    resp = requests.get(
        f"{base_url}/flights",
        params={"origin": "SVO", "destination": "LED", "date": "bad-date"},
        timeout=5,
    )
    assert resp.status_code == 400


@pytest.mark.e2e
def test_missing_query_params():
    base_url = "http://localhost:8000"
    resp = requests.get(f"{base_url}/flights?origin=SVO", timeout=5)
    assert resp.status_code == 422


@pytest.mark.e2e
def test_get_flight_not_found():
    base_url = "http://localhost:8000"
    resp = requests.get(f"{base_url}/flights/{uuid.uuid4()}", timeout=5)
    assert resp.status_code == 404


@pytest.mark.e2e
def test_create_booking_flight_not_found():
    base_url = "http://localhost:8000"
    payload = {
        "user_id": "u3",
        "flight_id": str(uuid.uuid4()),
        "passenger_name": "Eve",
        "passenger_email": "eve@example.com",
        "seat_count": 1,
    }
    booking = requests.post(f"{base_url}/bookings", json=payload, timeout=5)
    assert booking.status_code == 404


@pytest.mark.e2e
def test_create_booking_invalid_payload():
    base_url = "http://localhost:8000"
    payload = {
        "user_id": "u4",
        "flight_id": str(uuid.uuid4()),
        "passenger_name": "Eve",
        "passenger_email": "eve@example.com",
        "seat_count": 0,
    }
    booking = requests.post(f"{base_url}/bookings", json=payload, timeout=5)
    assert booking.status_code == 422
