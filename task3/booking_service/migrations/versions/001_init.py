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
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("flight_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_name", sa.String(length=128), nullable=False),
        sa.Column("passenger_email", sa.String(length=256), nullable=False),
        sa.Column("seat_count", sa.Integer(), nullable=False),
        sa.Column("total_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.Enum("CONFIRMED", "CANCELLED", name="bookingstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("seat_count > 0", name="ck_booking_seat_count_positive"),
        sa.CheckConstraint("total_price > 0", name="ck_total_price_positive"),
    )


def downgrade() -> None:
    op.drop_table("bookings")
    op.execute("DROP TYPE IF EXISTS bookingstatus")
