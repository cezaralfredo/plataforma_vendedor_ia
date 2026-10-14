"""Add the singleton administrative account.

Revision ID: 8d3f6a1c5b7e
Revises: 7e1c3a9d4b6f
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8d3f6a1c5b7e"
down_revision: str | None = "7e1c3a9d4b6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "auth_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("id = 1", name="ck_admin_accounts_singleton"),
        sa.UniqueConstraint("username", name="uq_admin_accounts_username"),
    )


def downgrade() -> None:
    op.drop_table("admin_accounts")
