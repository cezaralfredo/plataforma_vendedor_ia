"""Add client delivery address fields and branch address fields.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # 1. Campos de endereço completo e logística de entrega na tabela users
    if "users" in existing_tables:
        existing_user_cols = {c["name"] for c in insp.get_columns("users")}
        if "address_number" not in existing_user_cols:
            op.add_column("users", sa.Column("address_number", sa.String(length=30), nullable=True))
        if "address_complement" not in existing_user_cols:
            op.add_column("users", sa.Column("address_complement", sa.String(length=100), nullable=True))
        if "neighborhood" not in existing_user_cols:
            op.add_column("users", sa.Column("neighborhood", sa.String(length=100), nullable=True))
        if "delivery_instructions" not in existing_user_cols:
            op.add_column("users", sa.Column("delivery_instructions", sa.Text(), nullable=True))

        # Preencher registros existentes onde whatsapp_number ou address estiverem nulos
        if "whatsapp_number" in existing_user_cols and "phone" in existing_user_cols:
            op.execute("UPDATE users SET whatsapp_number = phone WHERE whatsapp_number IS NULL OR whatsapp_number = ''")
        if "address" in existing_user_cols:
            op.execute("UPDATE users SET address = 'Não informado' WHERE address IS NULL OR address = ''")

    # 2. Campos adicionais na tabela branches (Lojas)
    if "branches" in existing_tables:
        existing_branch_cols = {c["name"] for c in insp.get_columns("branches")}
        if "email" not in existing_branch_cols:
            op.add_column("branches", sa.Column("email", sa.String(length=255), nullable=True))
        if "postal_code" not in existing_branch_cols:
            op.add_column("branches", sa.Column("postal_code", sa.String(length=20), nullable=True))
        if "address_number" not in existing_branch_cols:
            op.add_column("branches", sa.Column("address_number", sa.String(length=30), nullable=True))
        if "neighborhood" not in existing_branch_cols:
            op.add_column("branches", sa.Column("neighborhood", sa.String(length=100), nullable=True))


def downgrade() -> None:
    # 2. Reverter branches
    op.drop_column("branches", "neighborhood")
    op.drop_column("branches", "address_number")
    op.drop_column("branches", "postal_code")
    op.drop_column("branches", "email")

    # 1. Reverter users
    op.drop_column("users", "delivery_instructions")
    op.drop_column("users", "neighborhood")
    op.drop_column("users", "address_complement")
    op.drop_column("users", "address_number")
