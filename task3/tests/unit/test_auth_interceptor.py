import os

import grpc
import pytest

from flight_service.app.auth import AuthInterceptor


class DummyHandlerCallDetails:
    def __init__(self, metadata):
        self.invocation_metadata = metadata


class DummyContext:
    def abort(self, code, details):
        raise grpc.RpcError((code, details))


@pytest.mark.unit
def test_auth_interceptor_rejects_invalid_key(monkeypatch):
    monkeypatch.setenv("GRPC_API_KEY", "secret")
    interceptor = AuthInterceptor()

    handler = interceptor.intercept_service(
        lambda _details: None,
        DummyHandlerCallDetails(metadata=(("x-api-key", "bad"),)),
    )

    with pytest.raises(grpc.RpcError):
        handler.unary_unary(None, DummyContext())


@pytest.mark.unit
def test_auth_interceptor_allows_valid_key(monkeypatch):
    monkeypatch.setenv("GRPC_API_KEY", "secret")
    interceptor = AuthInterceptor()

    called = {"ok": False}

    def cont(_details):
        def ok_handler(request, context):
            called["ok"] = True
            return None
        return grpc.unary_unary_rpc_method_handler(ok_handler)

    handler = interceptor.intercept_service(
        cont,
        DummyHandlerCallDetails(metadata=(("x-api-key", "secret"),)),
    )
    handler.unary_unary(None, DummyContext())
    assert called["ok"] is True
