"""Add durable payment notification outbox.

Revision ID: b5e8a1c3d6f0
Revises: a4c7e2f9b1d6
"""

import sqlalchemy as sa

from alembic import op

revision = "b5e8a1c3d6f0"
down_revision = "a4c7e2f9b1d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False, server_default="payment.confirmed"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=160), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('pending', 'processing', 'sent', 'failed')", name="check_notification_delivery_status"),
        sa.CheckConstraint("attempts >= 0", name="check_notification_delivery_attempts"),
        sa.UniqueConstraint("payment_id", "event", name="uq_notification_delivery_payment_event"),
    )
    op.create_index("ix_notification_deliveries_appointment_id", "notification_deliveries", ["appointment_id"])
    op.create_index("ix_notification_deliveries_payment_id", "notification_deliveries", ["payment_id"])
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])
    op.create_index("ix_notification_deliveries_next_attempt_at", "notification_deliveries", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_table("notification_deliveries")
