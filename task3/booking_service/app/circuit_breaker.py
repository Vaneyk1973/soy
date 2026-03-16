import logging
import os
import time
from collections import deque

import grpc

logger = logging.getLogger(__name__)


class CircuitBreakerOpen(Exception):
    pass


class CircuitBreaker:
    def __init__(self) -> None:
        self._state = "CLOSED"
        self._failure_threshold = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
        self._open_timeout = float(os.getenv("CB_OPEN_TIMEOUT_SEC", "15"))
        self._window_sec = float(os.getenv("CB_WINDOW_SEC", "60"))
        self._failures = deque()
        self._opened_at = None
        self._half_open_trial_in_flight = False

    def allow_request(self) -> None:
        now = time.time()
        if self._state == "OPEN":
            if self._opened_at and now - self._opened_at >= self._open_timeout:
                self._transition("HALF_OPEN")
            else:
                raise CircuitBreakerOpen("circuit breaker is open")
        if self._state == "HALF_OPEN":
            if self._half_open_trial_in_flight:
                raise CircuitBreakerOpen("circuit breaker half-open; trial in flight")
            self._half_open_trial_in_flight = True

    def record_success(self) -> None:
        if self._state in {"OPEN", "HALF_OPEN"}:
            self._transition("CLOSED")
        self._half_open_trial_in_flight = False
        self._failures.clear()

    def record_failure(self) -> None:
        now = time.time()
        self._half_open_trial_in_flight = False
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self._window_sec:
            self._failures.popleft()
        if self._state == "HALF_OPEN":
            self._transition("OPEN")
        elif len(self._failures) >= self._failure_threshold:
            self._transition("OPEN")

    def _transition(self, new_state: str) -> None:
        if self._state != new_state:
            logger.info("circuit breaker transition: %s -> %s", self._state, new_state)
        self._state = new_state
        if new_state == "OPEN":
            self._opened_at = time.time()
        else:
            self._opened_at = None


class CircuitBreakerInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, breaker: CircuitBreaker) -> None:
        self._breaker = breaker

    def intercept_unary_unary(self, continuation, client_call_details, request):
        self._breaker.allow_request()
        try:
            response = continuation(client_call_details, request)
        except grpc.RpcError:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return response
