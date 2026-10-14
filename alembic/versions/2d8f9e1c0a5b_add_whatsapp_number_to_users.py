"""add whatsapp_number to users

Revision ID: 2d8f9e1c0a5b
Revises: 1c4f5a6b7d8e
Create Date: 2026-08-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2d8f9e1c0a5b"
down_revision: Union[str, None] = "1c4f5a6b7d8e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("whatsapp_number", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_users_whatsapp_number", "users", ["whatsapp_number"]
    )


def downgrade() -> None:
    op.drop_index("ix_users_whatsapp_number", table_name="users")
    op.drop_column("users", "whatsapp_number")
