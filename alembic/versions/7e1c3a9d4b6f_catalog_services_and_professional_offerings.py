"""Create the service catalogue and professional commercial offerings.

Revision ID: 7e1c3a9d4b6f
Revises: 6d0b2f3e4a5c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7e1c3a9d4b6f"
down_revision: str | None = "6d0b2f3e4a5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.alter_column("services", "professional_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("services", "duration_minutes", existing_type=sa.Integer(), nullable=True)
    op.alter_column("services", "price_cents", existing_type=sa.Integer(), nullable=True)

    op.create_table(
        "professional_services",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("professional_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "commission_percent",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("10.00"),
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("price_cents >= 0", name="check_professional_service_price"),
        sa.CheckConstraint(
            "duration_minutes > 0", name="check_professional_service_duration"
        ),
        sa.CheckConstraint(
            "commission_percent >= 0 AND commission_percent <= 100",
            name="check_professional_service_commission",
        ),
        sa.ForeignKeyConstraint(["professional_id"], ["professionals.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.UniqueConstraint(
            "professional_id", "service_id", name="uq_professional_services_pair"
        ),
    )
    op.create_index(
        "ix_professional_services_professional_id",
        "professional_services",
        ["professional_id"],
    )
    op.create_index(
        "ix_professional_services_service_id",
        "professional_services",
        ["service_id"],
    )

    op.execute(
        """
        INSERT INTO professional_services
            (professional_id, service_id, price_cents, duration_minutes, commission_percent, active)
        SELECT professional_id, id, price_cents, duration_minutes, 10.00, true
        FROM services
        WHERE professional_id IS NOT NULL
          AND price_cents IS NOT NULL
          AND duration_minutes IS NOT NULL
        """
    )

    op.add_column("appointments", sa.Column("service_price_cents", sa.Integer(), nullable=True))
    op.add_column(
        "appointments", sa.Column("service_duration_minutes", sa.Integer(), nullable=True)
    )
    op.add_column(
        "appointments",
        sa.Column("professional_commission_percent", sa.Numeric(5, 2), nullable=True),
    )
    op.execute(
        """
        UPDATE appointments AS appointment
        SET service_price_cents = service.price_cents,
            service_duration_minutes = service.duration_minutes,
            professional_commission_percent = 10.00
        FROM services AS service
        WHERE appointment.service_id = service.id
        """
    )


def downgrade() -> None:
    op.drop_column("appointments", "professional_commission_percent")
    op.drop_column("appointments", "service_duration_minutes")
    op.drop_column("appointments", "service_price_cents")
    op.drop_index("ix_professional_services_service_id", table_name="professional_services")
    op.drop_index("ix_professional_services_professional_id", table_name="professional_services")
    op.drop_table("professional_services")
    op.alter_column("services", "price_cents", existing_type=sa.Integer(), nullable=False)
    op.alter_column("services", "duration_minutes", existing_type=sa.Integer(), nullable=False)
    op.alter_column("services", "professional_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("services", "active")
