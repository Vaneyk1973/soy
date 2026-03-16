import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Integer, Numeric, String, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID

from .db import Base


class BookingStatus(enum.Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(64), nullable=False)
    flight_id = Column(UUID(as_uuid=True), nullable=False)
    passenger_name = Column(String(128), nullable=False)
    passenger_email = Column(String(256), nullable=False)
    seat_count = Column(Integer, nullable=False)
    total_price = Column(Numeric(12, 2), nullable=False)
    status = Column(Enum(BookingStatus), nullable=False, default=BookingStatus.CONFIRMED)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("seat_count > 0", name="ck_booking_seat_count_positive"),
        CheckConstraint("total_price > 0", name="ck_total_price_positive"),
    )
