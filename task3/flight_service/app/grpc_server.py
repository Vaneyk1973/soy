import uuid
from datetime import datetime, timezone

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from sqlalchemy import select

from . import models
from .cache import Cache
from .db import SessionLocal
from .models import Flight, SeatReservation
from .generated import flight_pb2, flight_pb2_grpc

def _to_timestamp(dt: datetime) -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(dt.astimezone(timezone.utc))
    return ts


def _flight_to_proto(flight: Flight) -> flight_pb2.Flight:
    return flight_pb2.Flight(
        id=str(flight.id),
        flight_number=flight.flight_number,
        airline=flight.airline,
        origin=flight.origin,
        destination=flight.destination,
        departure_time=_to_timestamp(flight.departure_time),
        arrival_time=_to_timestamp(flight.arrival_time),
        total_seats=flight.total_seats,
        available_seats=flight.available_seats,
        price=int(flight.price * 100),
        status=flight_pb2.FlightStatus.Value(flight.status.value),
    )


def _flight_to_dict(proto: flight_pb2.Flight) -> dict:
    return {
        "id": proto.id,
        "flight_number": proto.flight_number,
        "airline": proto.airline,
        "origin": proto.origin,
        "destination": proto.destination,
        "departure_time": {"seconds": proto.departure_time.seconds, "nanos": proto.departure_time.nanos},
        "arrival_time": {"seconds": proto.arrival_time.seconds, "nanos": proto.arrival_time.nanos},
        "total_seats": proto.total_seats,
        "available_seats": proto.available_seats,
        "price": proto.price,
        "status": proto.status,
    }


def _dict_to_flight(payload: dict) -> flight_pb2.Flight:
    return flight_pb2.Flight(
        id=payload["id"],
        flight_number=payload["flight_number"],
        airline=payload["airline"],
        origin=payload["origin"],
        destination=payload["destination"],
        departure_time=Timestamp(**payload["departure_time"]),
        arrival_time=Timestamp(**payload["arrival_time"]),
        total_seats=payload["total_seats"],
        available_seats=payload["available_seats"],
        price=payload["price"],
        status=payload["status"],
    )

class FlightService(flight_pb2_grpc.FlightServiceServicer):
    def __init__(self) -> None:
        self._cache = Cache()

    def SearchFlights(self, request, context):
        cache_key = f"search:{request.origin}:{request.destination}:{request.date.seconds if request.HasField('date') else 'none'}"
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            flights = [_dict_to_flight(item) for item in cached["flights"]]
            return flight_pb2.SearchFlightsResponse(flights=flights)

        with SessionLocal() as session:
            stmt = select(Flight).where(
                Flight.origin == request.origin,
                Flight.destination == request.destination,
                Flight.status == models.FlightStatus.SCHEDULED,
            )
            if request.HasField("date"):
                search_date = datetime.fromtimestamp(request.date.seconds, tz=timezone.utc).date()
                stmt = stmt.where(Flight.departure_date == search_date)
            flights = session.execute(stmt).scalars().all()

        proto_flights = [_flight_to_proto(f) for f in flights]
        self._cache.set_json(cache_key, {"flights": [_flight_to_dict(item) for item in proto_flights]})
        return flight_pb2.SearchFlightsResponse(flights=proto_flights)

    def GetFlight(self, request, context):
        cache_key = f"flight:{request.id}"
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            return flight_pb2.GetFlightResponse(
                flight=_dict_to_flight(cached)
            )

        with SessionLocal() as session:
            try:
                flight_id = uuid.UUID(request.id)
            except ValueError:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid flight id")
            flight = session.get(Flight, flight_id)
            if not flight:
                context.abort(grpc.StatusCode.NOT_FOUND, "flight not found")
            proto = _flight_to_proto(flight)

        self._cache.set_json(cache_key, _flight_to_dict(proto))
        return flight_pb2.GetFlightResponse(flight=proto)

    def UpdateFlight(self, request, context):
        try:
            flight_id = uuid.UUID(request.id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid flight id")

        with SessionLocal() as session:
            with session.begin():
                flight = session.get(Flight, flight_id)
                if not flight:
                    context.abort(grpc.StatusCode.NOT_FOUND, "flight not found")
                if request.status != flight_pb2.FLIGHT_STATUS_UNSPECIFIED:
                    flight.status = models.FlightStatus(
                        flight_pb2.FlightStatus.Name(request.status)
                    )
                if request.price > 0:
                    flight.price = request.price / 100
                session.flush()
                proto = _flight_to_proto(flight)

        self._cache.delete(f"flight:{request.id}")
        self._cache.delete_pattern("search:*")
        return flight_pb2.UpdateFlightResponse(flight=proto)

    def ReserveSeats(self, request, context):
        if request.seat_count <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "seat_count must be positive")
        try:
            flight_id = uuid.UUID(request.flight_id)
            booking_id = uuid.UUID(request.booking_id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid flight_id or booking_id")

        with SessionLocal() as session:
            try:
                with session.begin():
                    existing = session.execute(
                        select(SeatReservation).where(SeatReservation.booking_id == booking_id)
                    ).scalar_one_or_none()
                    if existing:
                        if existing.flight_id != flight_id or existing.seat_count != request.seat_count:
                            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "booking_id already used with different data")
                        return flight_pb2.ReserveSeatsResponse(
                            reservation_id=str(existing.id),
                            status=flight_pb2.ReservationStatus.Value(existing.status.value),
                        )

                    flight = session.execute(
                        select(Flight).where(Flight.id == flight_id).with_for_update()
                    ).scalar_one_or_none()
                    if not flight:
                        context.abort(grpc.StatusCode.NOT_FOUND, "flight not found")
                    if flight.available_seats < request.seat_count:
                        context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "not enough seats")

                    flight.available_seats -= request.seat_count
                    reservation = SeatReservation(
                        booking_id=booking_id,
                        flight_id=flight.id,
                        seat_count=request.seat_count,
                        status=models.ReservationStatus.ACTIVE,
                    )
                    session.add(reservation)
                    session.flush()
                    reservation_id = str(reservation.id)
                    reservation_status = reservation.status
            except grpc.RpcError:
                raise

        self._cache.delete(f"flight:{request.flight_id}")
        self._cache.delete_pattern("search:*")
        return flight_pb2.ReserveSeatsResponse(
            reservation_id=reservation_id,
            status=flight_pb2.ReservationStatus.Value(reservation_status.value),
        )

    def ReleaseReservation(self, request, context):
        try:
            booking_id = uuid.UUID(request.booking_id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid booking_id")
        with SessionLocal() as session:
            try:
                with session.begin():
                    reservation = session.execute(
                        select(SeatReservation).where(
                            SeatReservation.booking_id == booking_id,
                            SeatReservation.status == models.ReservationStatus.ACTIVE,
                        ).with_for_update()
                    ).scalar_one_or_none()
                    if not reservation:
                        context.abort(grpc.StatusCode.NOT_FOUND, "reservation not found")
                    flight = session.execute(
                        select(Flight).where(Flight.id == reservation.flight_id).with_for_update()
                    ).scalar_one()
                    flight.available_seats += reservation.seat_count
                    reservation.status = models.ReservationStatus.RELEASED
                    session.flush()
                    reservation_id = str(reservation.id)
                    reservation_status = reservation.status
                    flight_id = reservation.flight_id
            except grpc.RpcError:
                raise

        self._cache.delete(f"flight:{flight_id}")
        self._cache.delete_pattern("search:*")
        return flight_pb2.ReleaseReservationResponse(
            reservation_id=reservation_id,
            status=flight_pb2.ReservationStatus.Value(reservation_status.value),
        )
