import uuid
from datetime import datetime, timezone, date

import grpc
import psycopg2
import pytest

from google.protobuf.timestamp_pb2 import Timestamp

import flight_pb2
import flight_pb2_grpc


@pytest.mark.integration
def test_flight_grpc_flow(flight_db_dsn, clean_dbs):
    flight_id = uuid.uuid4()
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

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
                    "SU123",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    100,
                    100,
                    15000.00,
                    "SCHEDULED",
                ),
            )
        conn.commit()

    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)

    search_ts = Timestamp()
    search_ts.FromDatetime(dep_time)
    search_resp = stub.SearchFlights(
        flight_pb2.SearchFlightsRequest(origin="SVO", destination="LED", date=search_ts),
        metadata=metadata,
        timeout=2,
    )
    assert len(search_resp.flights) == 1

    get_resp = stub.GetFlight(flight_pb2.GetFlightRequest(id=str(flight_id)), metadata=metadata, timeout=2)
    assert get_resp.flight.available_seats == 100

    booking_id = uuid.uuid4()
    reserve_resp = stub.ReserveSeats(
        flight_pb2.ReserveSeatsRequest(
            flight_id=str(flight_id),
            booking_id=str(booking_id),
            seat_count=2,
        ),
        metadata=metadata,
        timeout=2,
    )
    assert reserve_resp.status == flight_pb2.ACTIVE

    reserve_resp_2 = stub.ReserveSeats(
        flight_pb2.ReserveSeatsRequest(
            flight_id=str(flight_id),
            booking_id=str(booking_id),
            seat_count=2,
        ),
        metadata=metadata,
        timeout=2,
    )
    assert reserve_resp_2.reservation_id == reserve_resp.reservation_id

    release_resp = stub.ReleaseReservation(
        flight_pb2.ReleaseReservationRequest(booking_id=str(booking_id)),
        metadata=metadata,
        timeout=2,
    )
    assert release_resp.status == flight_pb2.RELEASED


@pytest.mark.integration
def test_unauthenticated_rejected():
    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    try:
        stub.GetFlight(flight_pb2.GetFlightRequest(id="00000000-0000-0000-0000-000000000000"), timeout=2)
        assert False, "expected UNAUTHENTICATED"
    except grpc.RpcError as exc:
        assert exc.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.integration
def test_invalid_flight_id_rejected():
    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)
    try:
        stub.GetFlight(flight_pb2.GetFlightRequest(id="not-a-uuid"), metadata=metadata, timeout=2)
        assert False, "expected INVALID_ARGUMENT"
    except grpc.RpcError as exc:
        assert exc.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.integration
def test_reserve_insufficient_seats(flight_db_dsn, clean_dbs):
    flight_id = uuid.uuid4()
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

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
                    "SU999",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    1,
                    1,
                    1000.00,
                    "SCHEDULED",
                ),
            )
        conn.commit()

    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)
    booking_id = uuid.uuid4()
    try:
        stub.ReserveSeats(
            flight_pb2.ReserveSeatsRequest(
                flight_id=str(flight_id),
                booking_id=str(booking_id),
                seat_count=2,
            ),
            metadata=metadata,
            timeout=2,
        )
        assert False, "expected RESOURCE_EXHAUSTED"
    except grpc.RpcError as exc:
        assert exc.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


@pytest.mark.integration
def test_release_missing_reservation():
    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)
    try:
        stub.ReleaseReservation(
            flight_pb2.ReleaseReservationRequest(booking_id=str(uuid.uuid4())),
            metadata=metadata,
            timeout=2,
        )
        assert False, "expected NOT_FOUND"
    except grpc.RpcError as exc:
        assert exc.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.integration
def test_get_flight_not_found():
    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)
    try:
        stub.GetFlight(
            flight_pb2.GetFlightRequest(id=str(uuid.uuid4())),
            metadata=metadata,
            timeout=2,
        )
        assert False, "expected NOT_FOUND"
    except grpc.RpcError as exc:
        assert exc.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.integration
def test_cache_invalidation_after_reserve(flight_db_dsn, clean_dbs):
    flight_id = uuid.uuid4()
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

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
                    "SU555",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    5,
                    5,
                    1000.00,
                    "SCHEDULED",
                ),
            )
        conn.commit()

    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)

    first = stub.GetFlight(flight_pb2.GetFlightRequest(id=str(flight_id)), metadata=metadata, timeout=2)
    assert first.flight.available_seats == 5

    stub.ReserveSeats(
        flight_pb2.ReserveSeatsRequest(
            flight_id=str(flight_id),
            booking_id=str(uuid.uuid4()),
            seat_count=2,
        ),
        metadata=metadata,
        timeout=2,
    )

    second = stub.GetFlight(flight_pb2.GetFlightRequest(id=str(flight_id)), metadata=metadata, timeout=2)
    assert second.flight.available_seats == 3


@pytest.mark.integration
def test_reserve_invalid_seat_count(flight_db_dsn, clean_dbs):
    flight_id = uuid.uuid4()
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

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
                    "SU100",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    10,
                    10,
                    1000.00,
                    "SCHEDULED",
                ),
            )
        conn.commit()

    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)
    try:
        stub.ReserveSeats(
            flight_pb2.ReserveSeatsRequest(
                flight_id=str(flight_id),
                booking_id=str(uuid.uuid4()),
                seat_count=0,
            ),
            metadata=metadata,
            timeout=2,
        )
        assert False, "expected INVALID_ARGUMENT"
    except grpc.RpcError as exc:
        assert exc.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.integration
def test_reserve_idempotency_mismatch(flight_db_dsn, clean_dbs):
    flight_id = uuid.uuid4()
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

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
                    "SU101",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    10,
                    10,
                    1000.00,
                    "SCHEDULED",
                ),
            )
        conn.commit()

    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)
    booking_id = uuid.uuid4()
    stub.ReserveSeats(
        flight_pb2.ReserveSeatsRequest(
            flight_id=str(flight_id),
            booking_id=str(booking_id),
            seat_count=1,
        ),
        metadata=metadata,
        timeout=2,
    )
    try:
        stub.ReserveSeats(
            flight_pb2.ReserveSeatsRequest(
                flight_id=str(flight_id),
                booking_id=str(booking_id),
                seat_count=2,
            ),
            metadata=metadata,
            timeout=2,
        )
        assert False, "expected INVALID_ARGUMENT"
    except grpc.RpcError as exc:
        assert exc.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.integration
def test_search_excludes_non_scheduled(flight_db_dsn, clean_dbs):
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

    with psycopg2.connect(flight_db_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO flights (id, flight_number, airline, origin, destination, departure_time, departure_date,
                                    arrival_time, total_seats, available_seats, price, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    str(uuid.uuid4()),
                    "SU777",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    10,
                    10,
                    1000.00,
                    "CANCELLED",
                ),
            )
        conn.commit()

    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)
    ts = Timestamp()
    ts.FromDatetime(dep_time)
    resp = stub.SearchFlights(
        flight_pb2.SearchFlightsRequest(origin="SVO", destination="LED", date=ts),
        metadata=metadata,
        timeout=2,
    )
    assert len(resp.flights) == 0


@pytest.mark.integration
def test_update_flight_invalidates_cache(flight_db_dsn, clean_dbs):
    flight_id = uuid.uuid4()
    dep_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    arr_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)

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
                    "SU888",
                    "SU",
                    "SVO",
                    "LED",
                    dep_time,
                    date(2026, 4, 1),
                    arr_time,
                    10,
                    10,
                    1000.00,
                    "SCHEDULED",
                ),
            )
        conn.commit()

    channel = grpc.insecure_channel("localhost:50051")
    stub = flight_pb2_grpc.FlightServiceStub(channel)
    metadata = (("x-api-key", "flight-api-key"),)

    before = stub.GetFlight(flight_pb2.GetFlightRequest(id=str(flight_id)), metadata=metadata, timeout=2)
    assert before.flight.price == 1000_00

    updated = stub.UpdateFlight(
        flight_pb2.UpdateFlightRequest(id=str(flight_id), status=flight_pb2.DEPARTED, price=2000_00),
        metadata=metadata,
        timeout=2,
    )
    assert updated.flight.status == flight_pb2.DEPARTED

    after = stub.GetFlight(flight_pb2.GetFlightRequest(id=str(flight_id)), metadata=metadata, timeout=2)
    assert after.flight.price == 2000_00
