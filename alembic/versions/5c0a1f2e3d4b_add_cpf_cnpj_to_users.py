"""add cpf_cnpj to users

Revision ID: 5c0a1f2e3d4b
Revises: 4a6f9d2e1b3c
Create Date: 2026-08-29

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5c0a1f2e3d4b"
down_revision: str | None = "4a6f9d2e1b3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("cpf_cnpj", sa.String(length=20), nullable=True),
    )
    op.create_index("ix_users_cpf_cnpj", "users", ["cpf_cnpj"])


def downgrade() -> None:
    op.drop_index("ix_users_cpf_cnpj", table_name="users")
    op.drop_column("users", "cpf_cnpj")
