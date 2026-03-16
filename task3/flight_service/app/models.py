import enum
import uuid
from datetime import datetime, date

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .db import Base


class FlightStatus(enum.Enum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ReservationStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class Flight(Base):
    __tablename__ = "flights"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flight_number = Column(String(16), nullable=False)
    airline = Column(String(64), nullable=False)
    origin = Column(String(3), nullable=False)
    destination = Column(String(3), nullable=False)
    departure_time = Column(DateTime(timezone=True), nullable=False)
    departure_date = Column(Date, nullable=False)
    arrival_time = Column(DateTime(timezone=True), nullable=False)
    total_seats = Column(Integer, nullable=False)
    available_seats = Column(Integer, nullable=False)
    price = Column(Numeric(12, 2), nullable=False)
    status = Column(Enum(FlightStatus), nullable=False, default=FlightStatus.SCHEDULED)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    reservations = relationship("SeatReservation", back_populates="flight")

    __table_args__ = (
        UniqueConstraint("flight_number", "departure_date", name="uq_flight_number_date"),
        CheckConstraint("total_seats > 0", name="ck_total_seats_positive"),
        CheckConstraint("available_seats >= 0", name="ck_available_seats_non_negative"),
        CheckConstraint("available_seats <= total_seats", name="ck_available_seats_lte_total"),
        CheckConstraint("price > 0", name="ck_price_positive"),
    )


class SeatReservation(Base):
    __tablename__ = "seat_reservations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    flight_id = Column(UUID(as_uuid=True), ForeignKey("flights.id"), nullable=False)
    seat_count = Column(Integer, nullable=False)
    status = Column(Enum(ReservationStatus), nullable=False, default=ReservationStatus.ACTIVE)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    flight = relationship("Flight", back_populates="reservations")

    __table_args__ = (
        CheckConstraint("seat_count > 0", name="ck_seat_count_positive"),
    )
