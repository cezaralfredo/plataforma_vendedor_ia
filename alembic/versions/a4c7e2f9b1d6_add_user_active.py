"""Add lifecycle state to clients.

Revision ID: a4c7e2f9b1d6
Revises: 9f2a4c6e8b1d
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4c7e2f9b1d6"
down_revision: str | None = "9f2a4c6e8b1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "active")
