import logging
import uuid
import os
from datetime import datetime, date as date_cls, time, timezone
from decimal import Decimal
from typing import Optional

import grpc
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .circuit_breaker import CircuitBreakerOpen
from .db import SessionLocal
from .grpc_client import FlightClient
from .models import Booking, BookingStatus
try:
    from .generated import flight_pb2
except ImportError:  # tests load generated protos from tests/generated
    import flight_pb2  # type: ignore
from .schemas import BookingCreate, BookingOut, BookingList, FlightOut

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI()
flight_client = FlightClient()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _flight_to_out(flight) -> FlightOut:
    return FlightOut(
        id=flight.id,
        flight_number=flight.flight_number,
        airline=flight.airline,
        origin=flight.origin,
        destination=flight.destination,
        departure_time=flight.departure_time.ToDatetime(),
        arrival_time=flight.arrival_time.ToDatetime(),
        total_seats=flight.total_seats,
        available_seats=flight.available_seats,
        price=flight.price / 100,
        status=flight_pb2.FlightStatus.Name(flight.status),
    )


@app.get("/flights", response_model=list[FlightOut])
def search_flights(
    origin: str = Query(...),
    destination: str = Query(...),
    date: Optional[str] = Query(None),
):
    try:
        search_date = (
            datetime.combine(date_cls.fromisoformat(date), time.min, tzinfo=timezone.utc)
            if date else None
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date format; use YYYY-MM-DD")

    try:
        response = flight_client.search_flights(origin, destination, search_date)
    except CircuitBreakerOpen:
        raise HTTPException(status_code=503, detail="flight service unavailable")
    except grpc.RpcError as exc:
        _raise_from_grpc(exc)

    return [_flight_to_out(f) for f in response.flights]


@app.get("/flights/{flight_id}", response_model=FlightOut)
def get_flight(flight_id: str):
    try:
        response = flight_client.get_flight(flight_id)
    except CircuitBreakerOpen:
        raise HTTPException(status_code=503, detail="flight service unavailable")
    except grpc.RpcError as exc:
        _raise_from_grpc(exc)

    return _flight_to_out(response.flight)


@app.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking(payload: BookingCreate, db: Session = Depends(get_db)):
    try:
        flight_response = flight_client.get_flight(payload.flight_id)
    except CircuitBreakerOpen:
        raise HTTPException(status_code=503, detail="flight service unavailable")
    except grpc.RpcError as exc:
        _raise_from_grpc(exc)

    booking_id = uuid.uuid4()
    try:
        flight_client.reserve_seats(payload.flight_id, str(booking_id), payload.seat_count)
    except CircuitBreakerOpen:
        raise HTTPException(status_code=503, detail="flight service unavailable")
    except grpc.RpcError as exc:
        _raise_from_grpc(exc)

    total_price = Decimal(flight_response.flight.price) / Decimal(100) * Decimal(payload.seat_count)
    booking = Booking(
        id=booking_id,
        user_id=payload.user_id,
        flight_id=payload.flight_id,
        passenger_name=payload.passenger_name,
        passenger_email=payload.passenger_email,
        seat_count=payload.seat_count,
        total_price=total_price,
        status=BookingStatus.CONFIRMED,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    return _booking_to_out(booking)


@app.get("/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: str, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="booking not found")
    return _booking_to_out(booking)


@app.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: str, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="booking not found")
    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(status_code=409, detail="booking already cancelled")

    try:
        flight_client.release_reservation(str(booking.id))
    except CircuitBreakerOpen:
        raise HTTPException(status_code=503, detail="flight service unavailable")
    except grpc.RpcError as exc:
        if exc.code() != grpc.StatusCode.NOT_FOUND:
            _raise_from_grpc(exc)

    booking.status = BookingStatus.CANCELLED
    db.commit()
    db.refresh(booking)
    return _booking_to_out(booking)


@app.get("/bookings", response_model=BookingList)
def list_bookings(user_id: str = Query(...), db: Session = Depends(get_db)):
    items = db.execute(select(Booking).where(Booking.user_id == user_id)).scalars().all()
    return BookingList(items=[_booking_to_out(item) for item in items])


def _booking_to_out(booking: Booking) -> BookingOut:
    return BookingOut(
        id=str(booking.id),
        user_id=booking.user_id,
        flight_id=str(booking.flight_id),
        passenger_name=booking.passenger_name,
        passenger_email=booking.passenger_email,
        seat_count=booking.seat_count,
        total_price=float(booking.total_price),
        status=booking.status.value,
        created_at=booking.created_at,
    )


def _raise_from_grpc(exc: grpc.RpcError) -> None:
    code = exc.code()
    if code == grpc.StatusCode.NOT_FOUND:
        raise HTTPException(status_code=404, detail=exc.details())
    if code == grpc.StatusCode.RESOURCE_EXHAUSTED:
        raise HTTPException(status_code=409, detail=exc.details())
    if code == grpc.StatusCode.INVALID_ARGUMENT:
        raise HTTPException(status_code=400, detail=exc.details())
    if code == grpc.StatusCode.UNAUTHENTICATED:
        raise HTTPException(status_code=503, detail="flight service auth failed")
    raise HTTPException(status_code=502, detail="flight service error")
