from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BookingCreate(BaseModel):
    user_id: str
    flight_id: str
    passenger_name: str
    passenger_email: str
    seat_count: int = Field(gt=0)


class BookingOut(BaseModel):
    id: str
    user_id: str
    flight_id: str
    passenger_name: str
    passenger_email: str
    seat_count: int
    total_price: float
    status: str
    created_at: datetime


class FlightOut(BaseModel):
    id: str
    flight_number: str
    airline: str
    origin: str
    destination: str
    departure_time: datetime
    arrival_time: datetime
    total_seats: int
    available_seats: int
    price: float
    status: str


class BookingList(BaseModel):
    items: list[BookingOut]
