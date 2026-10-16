"""Add deliveries table and client preferred bank.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Campo banco de preferência do cliente na tabela users
    op.add_column("users", sa.Column("preferred_bank", sa.String(length=100), nullable=True))

    # 2. Tabela de Entregas e Logística
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_code", sa.String(length=30), nullable=False, unique=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("seller_id", sa.Integer(), sa.ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("items_description", sa.Text(), nullable=False),
        sa.Column("total_amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payment_method", sa.String(length=30), nullable=False, server_default="pix"),
        sa.Column("payment_timing", sa.String(length=20), nullable=False, server_default="na_entrega"),
        sa.Column("payment_status", sa.String(length=20), nullable=False, server_default="pendente"),
        sa.Column("delivery_status", sa.String(length=30), nullable=False, server_default="preparando"),
        sa.Column("delivery_address", sa.Text(), nullable=False),
        sa.Column("delivery_driver_name", sa.String(length=100), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("deliveries")
    op.drop_column("users", "preferred_bank")
