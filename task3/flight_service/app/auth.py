import os
import grpc


class AuthInterceptor(grpc.ServerInterceptor):
    def __init__(self) -> None:
        self._api_key = os.getenv("GRPC_API_KEY")
        if not self._api_key:
            raise RuntimeError("GRPC_API_KEY is not set")

    def intercept_service(self, continuation, handler_call_details):
        metadata = dict(handler_call_details.invocation_metadata or [])
        api_key = metadata.get("x-api-key")
        if api_key != self._api_key:
            def abort(request, context):
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid api key")
            return grpc.unary_unary_rpc_method_handler(abort)
        return continuation(handler_call_details)
