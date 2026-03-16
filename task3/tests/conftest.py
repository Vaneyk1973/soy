import os
import sys
import subprocess
from pathlib import Path

import pytest
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
PROTO_SRC = ROOT / "proto" / "flight.proto"
GENERATED_DIR = ROOT / "tests" / "generated"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_proto_generated():
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    init_file = GENERATED_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{ROOT / 'proto'}",
            f"--python_out={GENERATED_DIR}",
            f"--grpc_python_out={GENERATED_DIR}",
            str(PROTO_SRC),
        ],
        check=True,
    )
    if str(GENERATED_DIR) not in sys.path:
        sys.path.insert(0, str(GENERATED_DIR))


_ensure_proto_generated()


@pytest.fixture(scope="session", autouse=True)
def generate_proto():
    return None


@pytest.fixture(scope="session")
def booking_db_dsn():
    return os.getenv("BOOKING_TEST_DB_DSN", "postgresql://booking:booking@localhost:5433/booking")


@pytest.fixture(scope="session")
def flight_db_dsn():
    return os.getenv("FLIGHT_TEST_DB_DSN", "postgresql://flight:flight@localhost:5434/flight")


@pytest.fixture()
def clean_dbs(booking_db_dsn, flight_db_dsn):
    with psycopg2.connect(booking_db_dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bookings")
    with psycopg2.connect(flight_db_dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM seat_reservations")
            cur.execute("DELETE FROM flights")
    yield
    with psycopg2.connect(booking_db_dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bookings")
    with psycopg2.connect(flight_db_dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM seat_reservations")
            cur.execute("DELETE FROM flights")
