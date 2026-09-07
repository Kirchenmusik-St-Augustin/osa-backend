"""add money check constraints

Revision ID: 521f1ba5e919
Revises: 2daa19164273
Create Date: 2026-09-07 13:00:20.081183

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "521f1ba5e919"
down_revision: str | Sequence[str] | None = "2daa19164273"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint("fees_amount_check", "fees", "amount >= 0")
    op.create_check_constraint("bookings_fee_check", "bookings", "fee >= 0")
    op.create_check_constraint("booking_logs_fee_check", "booking_logs", "fee >= 0")
    op.create_check_constraint(
        "performances_choirjob_defaultfee_check",
        "performances",
        "choirjob_defaultfee >= 0",
    )
    op.create_check_constraint(
        "performances_instrument_defaultfee_check",
        "performances",
        "instrument_defaultfee >= 0",
    )
    op.create_check_constraint(
        "performances_voice_defaultfee_check", "performances", "voice_defaultfee >= 0"
    )
    op.create_check_constraint(
        "performances_extracost_amount_check",
        "performances",
        "extracost_amount IS NULL OR extracost_amount >= 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "performances_extracost_amount_check", "performances", type_="check"
    )
    op.drop_constraint(
        "performances_voice_defaultfee_check", "performances", type_="check"
    )
    op.drop_constraint(
        "performances_instrument_defaultfee_check", "performances", type_="check"
    )
    op.drop_constraint(
        "performances_choirjob_defaultfee_check", "performances", type_="check"
    )
    op.drop_constraint("booking_logs_fee_check", "booking_logs", type_="check")
    op.drop_constraint("bookings_fee_check", "bookings", type_="check")
    op.drop_constraint("fees_amount_check", "fees", type_="check")
