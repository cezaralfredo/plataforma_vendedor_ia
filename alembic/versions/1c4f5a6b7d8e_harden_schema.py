"""Align the production schema with the application models.

Revision ID: 1c4f5a6b7d8e
Revises: 7b4e3c7db79e
"""

import sqlalchemy as sa

from alembic import op

revision = "1c4f5a6b7d8e"
down_revision = "7b4e3c7db79e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial revision stored temporal values as strings.  Explicit casts
    # preserve already persisted ISO values while making comparisons reliable.
    op.execute("ALTER TABLE users ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at::timestamptz")
    op.execute("ALTER TABLE availability ALTER COLUMN start_time TYPE TIME USING start_time::time")
    op.execute("ALTER TABLE availability ALTER COLUMN end_time TYPE TIME USING end_time::time")
    op.execute("ALTER TABLE availability ALTER COLUMN specific_date TYPE DATE USING specific_date::date")
    op.execute("ALTER TABLE appointments ALTER COLUMN start_time TYPE TIMESTAMP WITH TIME ZONE USING start_time::timestamptz")
    op.execute("ALTER TABLE appointments ALTER COLUMN end_time TYPE TIMESTAMP WITH TIME ZONE USING end_time::timestamptz")
    op.execute("ALTER TABLE appointments ALTER COLUMN expires_at TYPE TIMESTAMP WITH TIME ZONE USING expires_at::timestamptz")
    op.execute("ALTER TABLE appointments ALTER COLUMN notified_at TYPE TIMESTAMP WITH TIME ZONE USING notified_at::timestamptz")
    op.execute("ALTER TABLE appointments ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at::timestamptz")
    op.execute("ALTER TABLE notification_log ALTER COLUMN sent_at TYPE TIMESTAMP WITH TIME ZONE USING sent_at::timestamptz")
    op.execute("ALTER TABLE payments ALTER COLUMN received_at TYPE TIMESTAMP WITH TIME ZONE USING received_at::timestamptz")
    op.execute("ALTER TABLE payments ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at::timestamptz")
    op.execute("ALTER TABLE payments ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING updated_at::timestamptz")

    for table in ("users", "appointments", "payments"):
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )

    for table in ("professionals", "services", "availability"):
        op.add_column(table, sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))

    op.execute("UPDATE payments SET billing_type = lower(billing_type)")
    op.create_unique_constraint("uq_payments_asaas_payment_id", "payments", ["asaas_payment_id"])
    op.create_index("ix_payments_appointment_id", "payments", ["appointment_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_appointments_user_id", "appointments", ["user_id"])
    op.create_index("ix_appointments_professional_id", "appointments", ["professional_id"])
    op.create_index("ix_appointments_start_time", "appointments", ["start_time"])
    op.create_index("ix_availability_professional_id", "availability", ["professional_id"])
    op.create_index("ix_availability_specific_date", "availability", ["specific_date"])

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider_event_id", sa.String(length=120), nullable=False, unique=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("webhook_events")
    for name, table in (
        ("ix_availability_specific_date", "availability"),
        ("ix_availability_professional_id", "availability"),
        ("ix_appointments_start_time", "appointments"),
        ("ix_appointments_professional_id", "appointments"),
        ("ix_appointments_user_id", "appointments"),
        ("ix_payments_status", "payments"),
        ("ix_payments_appointment_id", "payments"),
    ):
        op.drop_index(name, table_name=table)
    op.drop_constraint("uq_payments_asaas_payment_id", "payments", type_="unique")
    for table in ("availability", "services", "professionals"):
        op.drop_column(table, "created_at")
