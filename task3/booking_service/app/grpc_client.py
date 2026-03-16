import os
import time
from datetime import datetime, timezone

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpen, CircuitBreakerInterceptor

try:
    from .generated import flight_pb2, flight_pb2_grpc
except ImportError:  # tests load generated protos from tests/generated
    import flight_pb2  # type: ignore
    import flight_pb2_grpc  # type: ignore

RETRY_CODES = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}


class FlightClient:
    def __init__(self) -> None:
        self._target = os.getenv("FLIGHT_GRPC_TARGET", "flight-service:50051")
        self._api_key = os.getenv("GRPC_API_KEY")
        if not self._api_key:
            raise RuntimeError("GRPC_API_KEY is not set")
        breaker = CircuitBreaker()
        interceptor = CircuitBreakerInterceptor(breaker)
        self._timeout = float(os.getenv("GRPC_TIMEOUT_SEC", "2.0"))
        self._channel = grpc.intercept_channel(grpc.insecure_channel(self._target), interceptor)
        self._stub = flight_pb2_grpc.FlightServiceStub(self._channel)

    def _metadata(self):
        return (("x-api-key", self._api_key),)

    def _call_with_retry(self, func, request):
        attempts = 0
        backoff = 0.1
        while True:
            attempts += 1
            try:
                response = func(request, timeout=self._timeout, metadata=self._metadata())
                return response
            except CircuitBreakerOpen:
                raise
            except grpc.RpcError as exc:
                code = exc.code()
                if code in RETRY_CODES and attempts < 3:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise

    def search_flights(self, origin: str, destination: str, date: datetime | None):
        req = flight_pb2.SearchFlightsRequest(origin=origin, destination=destination)
        if date:
            ts = Timestamp()
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            ts.FromDatetime(date.astimezone(timezone.utc))
            req.date.CopyFrom(ts)
        return self._call_with_retry(self._stub.SearchFlights, req)

    def get_flight(self, flight_id: str):
        req = flight_pb2.GetFlightRequest(id=flight_id)
        return self._call_with_retry(self._stub.GetFlight, req)

    def reserve_seats(self, flight_id: str, booking_id: str, seat_count: int):
        req = flight_pb2.ReserveSeatsRequest(
            flight_id=flight_id,
            booking_id=booking_id,
            seat_count=seat_count,
        )
        return self._call_with_retry(self._stub.ReserveSeats, req)

    def release_reservation(self, booking_id: str):
        req = flight_pb2.ReleaseReservationRequest(booking_id=booking_id)
        return self._call_with_retry(self._stub.ReleaseReservation, req)
