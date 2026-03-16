import logging
import os
from concurrent import futures

import grpc

from .auth import AuthInterceptor
from .generated import flight_pb2_grpc
from .grpc_server import FlightService

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10), interceptors=[AuthInterceptor()])
    flight_pb2_grpc.add_FlightServiceServicer_to_server(FlightService(), server)
    port = os.getenv("GRPC_PORT", "50051")
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
