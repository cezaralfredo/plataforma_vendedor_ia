"""add admin_users table for panel login

Revision ID: 6d0b2f3e4a5c
Revises: 5c0a1f2e3d4b
Create Date: 2026-09-04

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6d0b2f3e4a5c"
down_revision: str | None = "5c0a1f2e3d4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
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
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_admin_users_username", "admin_users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_admin_users_username", table_name="admin_users")
    op.drop_table("admin_users")
