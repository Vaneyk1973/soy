import time

import pytest

from booking_service.app.circuit_breaker import CircuitBreaker, CircuitBreakerOpen


@pytest.mark.unit
def test_circuit_breaker_opens_after_threshold(monkeypatch):
    monkeypatch.setenv("CB_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("CB_OPEN_TIMEOUT_SEC", "1")
    monkeypatch.setenv("CB_WINDOW_SEC", "60")
    breaker = CircuitBreaker()

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_failure()

    try:
        breaker.allow_request()
        assert False, "expected CircuitBreakerOpen"
    except CircuitBreakerOpen:
        pass


@pytest.mark.unit
def test_circuit_breaker_half_open_and_close(monkeypatch):
    monkeypatch.setenv("CB_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("CB_OPEN_TIMEOUT_SEC", "0.1")
    monkeypatch.setenv("CB_WINDOW_SEC", "60")
    breaker = CircuitBreaker()

    breaker.record_failure()
    time.sleep(0.11)

    breaker.allow_request()
    breaker.record_success()

    breaker.allow_request()
