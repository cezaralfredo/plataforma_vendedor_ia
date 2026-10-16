"""Add company_settings and products tables for conversational commerce and modular settings.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Tabela company_settings
    op.create_table(
        "company_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "company_name",
            sa.String(length=100),
            nullable=False,
            server_default=sa.text("'Minha Empresa'"),
        ),
        sa.Column(
            "payment_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "default_gateway",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'asaas'"),
        ),
        sa.Column(
            "gateway_credentials",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "accepted_payment_methods",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"pix\"]'"),
        ),
        sa.Column(
            "commission_model",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'percentage'"),
        ),
        sa.Column(
            "default_commission_rate",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        sa.Column(
            "split_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "whatsapp_provider",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'evolution'"),
        ),
        sa.Column("evolution_instance", sa.String(length=100), nullable=True),
        sa.Column("meta_phone_number_id", sa.String(length=100), nullable=True),
        sa.Column("meta_access_token", sa.Text(), nullable=True),
        sa.Column("meta_waba_id", sa.String(length=100), nullable=True),
        sa.Column(
            "assistant_name",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'Assistente'"),
        ),
        sa.Column(
            "tone",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'casual'"),
        ),
        sa.Column(
            "require_cpf",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("welcome_message", sa.Text(), nullable=True),
        sa.Column(
            "custom_settings",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
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
    )

    # 2. Tabela products
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column(
            "stock_quantity",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("sku", sa.String(length=50), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
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
        sa.CheckConstraint("price_cents >= 0", name="check_product_price"),
        sa.CheckConstraint("stock_quantity >= 0", name="check_product_stock"),
    )
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_sku", "products", ["sku"])
    op.create_index("ix_products_active", "products", ["active"])


def downgrade() -> None:
    op.drop_index("ix_products_active", table_name="products")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_table("products")
    op.drop_table("company_settings")
