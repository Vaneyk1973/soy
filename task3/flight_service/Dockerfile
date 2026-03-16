FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY proto /app/proto
COPY app /app/app
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini

RUN python -m grpc_tools.protoc -I /app/proto --python_out /app/app/generated --grpc_python_out /app/app/generated /app/proto/flight.proto

ENV PYTHONPATH=/app:/app/app/generated

CMD alembic upgrade head && python -m app.main
