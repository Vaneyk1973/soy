"""init

Revision ID: 001
Revises: 
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flights",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("flight_number", sa.String(length=16), nullable=False),
        sa.Column("airline", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("departure_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column("arrival_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_seats", sa.Integer(), nullable=False),
        sa.Column("available_seats", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.Enum("SCHEDULED", "DEPARTED", "CANCELLED", "COMPLETED", name="flightstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_seats > 0", name="ck_total_seats_positive"),
        sa.CheckConstraint("available_seats >= 0", name="ck_available_seats_non_negative"),
        sa.CheckConstraint("available_seats <= total_seats", name="ck_available_seats_lte_total"),
        sa.CheckConstraint("price > 0", name="ck_price_positive"),
        sa.UniqueConstraint("flight_number", "departure_date", name="uq_flight_number_date"),
    )

    op.create_table(
        "seat_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("flight_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flights.id"), nullable=False),
        sa.Column("seat_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("ACTIVE", "RELEASED", "EXPIRED", name="reservationstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("seat_count > 0", name="ck_seat_count_positive"),
    )


def downgrade() -> None:
    op.drop_table("seat_reservations")
    op.drop_table("flights")
    op.execute("DROP TYPE IF EXISTS reservationstatus")
    op.execute("DROP TYPE IF EXISTS flightstatus")
