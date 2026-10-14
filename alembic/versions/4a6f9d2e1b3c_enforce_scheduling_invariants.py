"""Enforce scheduling and monetary invariants.

Revision ID: 4a6f9d2e1b3c
Revises: 2d8f9e1c0a5b
"""

import sqlalchemy as sa

from alembic import op

revision = "4a6f9d2e1b3c"
down_revision = "2d8f9e1c0a5b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM appointments a
            JOIN appointments b
              ON a.id < b.id
             AND a.professional_id = b.professional_id
             AND tstzrange(a.start_time, a.end_time, '[)')
                 && tstzrange(b.start_time, b.end_time, '[)')
             AND a.status IN ('pending', 'awaiting_payment', 'confirmed', 'completed')
             AND b.status IN ('pending', 'awaiting_payment', 'confirmed', 'completed')
          ) THEN
            RAISE EXCEPTION 'Resolve overlapping active appointments before migration';
          END IF;
        END $$;
        """
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_check_constraint(
        "check_appointment_interval", "appointments", "end_time > start_time"
    )
    op.create_check_constraint(
        "check_availability_interval",
        "availability",
        "start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time",
    )
    op.create_check_constraint(
        "check_service_duration", "services", "duration_minutes > 0"
    )
    op.create_check_constraint("check_service_price", "services", "price_cents >= 0")
    op.create_check_constraint("check_payment_amount", "payments", "amount_cents >= 0")
    op.create_exclude_constraint(
        "exclude_professional_overlapping_appointments",
        "appointments",
        ("professional_id", "="),
        (
            sa.func.tstzrange(
                sa.column("start_time"), sa.column("end_time"), "[)"
            ),
            "&&",
        ),
        where=sa.text(
            "status IN ('pending', 'awaiting_payment', 'confirmed', 'completed')"
        ),
        using="gist",
    )


def downgrade() -> None:
    op.drop_constraint(
        "exclude_professional_overlapping_appointments",
        "appointments",
        type_="exclude",
    )
    for name, table in (
        ("check_payment_amount", "payments"),
        ("check_service_price", "services"),
        ("check_service_duration", "services"),
        ("check_availability_interval", "availability"),
        ("check_appointment_interval", "appointments"),
    ):
        op.drop_constraint(name, table, type_="check")
