"""Add processed_inbound_messages table for webhook deduplication.

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f7
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "processed_inbound_messages" not in existing_tables:
        op.create_table(
            "processed_inbound_messages",
            sa.Column("message_id", sa.String(length=191), primary_key=True, nullable=False),
            sa.Column("provider", sa.String(length=30), nullable=True),
            sa.Column("phone", sa.String(length=50), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_processed_inbound_messages_created_at",
            "processed_inbound_messages",
            ["created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "processed_inbound_messages" in existing_tables:
        op.drop_index("ix_processed_inbound_messages_created_at", table_name="processed_inbound_messages")
        op.drop_table("processed_inbound_messages")
