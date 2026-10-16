"""Add branches and sellers tables and link them to payments.

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Tabela branches (Filiais)
    op.create_table(
        "branches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("cnpj", sa.String(length=20), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("whatsapp_number", sa.String(length=20), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_branches_code", "branches", ["code"], unique=True)
    op.create_index("ix_branches_whatsapp_number", "branches", ["whatsapp_number"])

    # 2. Tabela sellers (Vendedores das Filiais)
    op.create_table(
        "sellers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("whatsapp_number", sa.String(length=20), nullable=False),
        sa.Column("cpf", sa.String(length=20), nullable=True),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("commission_rate", sa.Numeric(precision=5, scale=2), server_default="0.0", nullable=False),
        sa.Column("pix_key", sa.String(length=100), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sellers_branch_id", "sellers", ["branch_id"])
    op.create_index("ix_sellers_email", "sellers", ["email"], unique=True)
    op.create_index("ix_sellers_code", "sellers", ["code"], unique=True)
    op.create_index("ix_sellers_whatsapp_number", "sellers", ["whatsapp_number"])
    op.create_index("ix_sellers_cpf", "sellers", ["cpf"])

    # 3. Adicionar campos de filial, vendedor e comissão à tabela payments
    op.add_column(
        "payments",
        sa.Column("branch_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("seller_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("commission_amount_cents", sa.Integer(), server_default="0", nullable=True),
    )
    op.create_foreign_key("fk_payments_branch_id", "payments", "branches", ["branch_id"], ["id"])
    op.create_foreign_key("fk_payments_seller_id", "payments", "sellers", ["seller_id"], ["id"])
    op.create_index("ix_payments_branch_id", "payments", ["branch_id"])
    op.create_index("ix_payments_seller_id", "payments", ["seller_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_seller_id", table_name="payments")
    op.drop_index("ix_payments_branch_id", table_name="payments")
    op.drop_constraint("fk_payments_seller_id", "payments", type_="foreignkey")
    op.drop_constraint("fk_payments_branch_id", "payments", type_="foreignkey")
    op.drop_column("payments", "commission_amount_cents")
    op.drop_column("payments", "seller_id")
    op.drop_column("payments", "branch_id")

    op.drop_index("ix_sellers_cpf", table_name="sellers")
    op.drop_index("ix_sellers_whatsapp_number", table_name="sellers")
    op.drop_index("ix_sellers_code", table_name="sellers")
    op.drop_index("ix_sellers_email", table_name="sellers")
    op.drop_index("ix_sellers_branch_id", table_name="sellers")
    op.drop_table("sellers")

    op.drop_index("ix_branches_whatsapp_number", table_name="branches")
    op.drop_index("ix_branches_code", table_name="branches")
    op.drop_table("branches")
