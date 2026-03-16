import uuid
from datetime import datetime, timezone, date

import psycopg2
import pytest


@pytest.mark.integration
def test_flight_constraints(flight_db_dsn, clean_dbs):
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

    with psycopg2.connect(flight_db_dsn) as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.Error):
                cur.execute(
                    """
                    INSERT INTO flights (id, flight_number, airline, origin, destination, departure_time, departure_date,
                                        arrival_time, total_seats, available_seats, price, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        str(uuid.uuid4()),
                        "SU001",
                        "SU",
                        "SVO",
                        "LED",
                        dep_time,
                        date(2026, 4, 1),
                        arr_time,
                        0,
                        -1,
                        -10.00,
                        "SCHEDULED",
                    ),
                )
            conn.rollback()

            flight_id = uuid.uuid4()
            cur.execute(
                """
                INSERT INTO flights (id, flight_number, airline, origin, destination, departure_time, departure_date,
                                    arrival_time, total_seats, available_seats, price, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    str(flight_id),
                    "SU003",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    10,
                    10,
                    10.00,
                    "SCHEDULED",
                ),
            )
            with pytest.raises(psycopg2.Error):
                cur.execute(
                    """
                    INSERT INTO seat_reservations (id, booking_id, flight_id, seat_count, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, now())
                    """,
                    (
                        str(uuid.uuid4()),
                        str(uuid.uuid4()),
                        str(flight_id),
                        0,
                        "ACTIVE",
                    ),
                )
            conn.rollback()

            cur.execute(
                """
                INSERT INTO flights (id, flight_number, airline, origin, destination, departure_time, departure_date,
                                    arrival_time, total_seats, available_seats, price, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    str(uuid.uuid4()),
                    "SU002",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    10,
                    10,
                    10.00,
                    "SCHEDULED",
                ),
            )
            with pytest.raises(psycopg2.Error):
                cur.execute(
                    """
                    INSERT INTO flights (id, flight_number, airline, origin, destination, departure_time, departure_date,
                                        arrival_time, total_seats, available_seats, price, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        str(uuid.uuid4()),
                        "SU002",
                        "SU",
                        "SVO",
                        "LED",
                        dep_time,
                        date(2026, 4, 1),
                        arr_time,
                        10,
                        10,
                        10.00,
                        "SCHEDULED",
                    ),
                )
            conn.rollback()

@pytest.mark.integration
def test_booking_constraints(booking_db_dsn, clean_dbs):
    with psycopg2.connect(booking_db_dsn) as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.Error):
                cur.execute(
                    """
                    INSERT INTO bookings (id, user_id, flight_id, passenger_name, passenger_email, seat_count, total_price, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        str(uuid.uuid4()),
                        "u1",
                        str(uuid.uuid4()),
                        "Alice",
                        "alice@example.com",
                        0,
                        -10.00,
                        "CONFIRMED",
                    ),
                )
