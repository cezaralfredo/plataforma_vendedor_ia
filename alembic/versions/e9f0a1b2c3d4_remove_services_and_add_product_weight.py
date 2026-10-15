"""Add product weight and decouple payments for direct sales.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Adicionar campo weight_kg à tabela products
    op.add_column(
        "products",
        sa.Column("weight_kg", sa.Numeric(precision=10, scale=3), nullable=True),
    )
    op.create_check_constraint(
        "check_product_weight",
        "products",
        "weight_kg IS NULL OR weight_kg >= 0",
    )

    # 2. Desacoplar pagamentos (tornar appointment_id opcional, adicionar user_id, product_id, description)
    op.add_column(
        "payments",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("description", sa.String(length=255), nullable=True),
    )
    op.alter_column(
        "payments",
        "appointment_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_product_id", "payments", ["product_id"])

    # 3. Tornar campos legados de agendamentos opcionais
    op.alter_column(
        "appointments",
        "professional_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "appointments",
        "service_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "appointments",
        "service_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "appointments",
        "professional_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_index("ix_payments_product_id", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.alter_column(
        "payments",
        "appointment_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("payments", "description")
    op.drop_column("payments", "product_id")
    op.drop_column("payments", "user_id")
    op.drop_constraint("check_product_weight", "products", type_="check")
    op.drop_column("products", "weight_kg")
