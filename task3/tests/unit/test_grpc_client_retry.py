import grpc
import time

import pytest

from booking_service.app.grpc_client import FlightClient


class DummyStub:
    def __init__(self, responses):
        self._responses = responses
        self.calls = 0

    def GetFlight(self, request, timeout=None, metadata=None):
        resp = self._responses[self.calls]
        self.calls += 1
        if isinstance(resp, Exception):
            raise resp
        return resp


class DummyRpcError(grpc.RpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code


class DummyResponse:
    pass


@pytest.mark.unit
def test_retry_on_unavailable(monkeypatch):
    monkeypatch.setenv("GRPC_API_KEY", "key")
    monkeypatch.setattr(time, "sleep", lambda _: None)
    client = FlightClient()
    client._stub = DummyStub([
        DummyRpcError(grpc.StatusCode.UNAVAILABLE),
        DummyResponse(),
    ])

    response = client.get_flight("abc")
    assert isinstance(response, DummyResponse)


@pytest.mark.unit
def test_no_retry_on_invalid_argument(monkeypatch):
    monkeypatch.setenv("GRPC_API_KEY", "key")
    monkeypatch.setattr(time, "sleep", lambda _: None)
    client = FlightClient()
    client._stub = DummyStub([
        DummyRpcError(grpc.StatusCode.INVALID_ARGUMENT),
    ])

    try:
        client.get_flight("abc")
        assert False, "expected error"
    except grpc.RpcError:
        pass


@pytest.mark.unit
def test_retry_backoff_sequence(monkeypatch):
    monkeypatch.setenv("GRPC_API_KEY", "key")
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    client = FlightClient()
    client._stub = DummyStub([
        DummyRpcError(grpc.StatusCode.UNAVAILABLE),
        DummyRpcError(grpc.StatusCode.UNAVAILABLE),
        DummyResponse(),
    ])

    response = client.get_flight("abc")
    assert isinstance(response, DummyResponse)
    assert sleeps == [0.1, 0.2]
