"""Add WAHA and multi-provider WhatsApp fields and chat messages.

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Adicionar colunas de conexão WhatsApp à tabela company_settings
    op.add_column(
        "company_settings",
        sa.Column("evolution_base_url", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "company_settings",
        sa.Column("evolution_api_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "company_settings",
        sa.Column("waha_base_url", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "company_settings",
        sa.Column("waha_session", sa.String(length=100), nullable=True, server_default="default"),
    )
    op.add_column(
        "company_settings",
        sa.Column("waha_api_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "company_settings",
        sa.Column("meta_verify_token", sa.String(length=100), nullable=True),
    )
    # Colunas de IA
    op.add_column(
        "company_settings",
        sa.Column("ai_provider", sa.String(length=30), nullable=False, server_default="openai"),
    )
    op.add_column(
        "company_settings",
        sa.Column("ai_model", sa.String(length=100), nullable=False, server_default="gpt-4o-mini"),
    )
    op.add_column(
        "company_settings",
        sa.Column("ai_api_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "company_settings",
        sa.Column("ai_base_url", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "company_settings",
        sa.Column("ai_temperature", sa.Numeric(precision=3, scale=2), nullable=False, server_default="0.30"),
    )
    op.add_column(
        "company_settings",
        sa.Column("ai_system_prompt", sa.Text(), nullable=True),
    )

    # 2. Criar tabela chat_messages para persistir histórico de conversas do WhatsApp
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_phone", "chat_messages", ["phone"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_phone", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_column("company_settings", "meta_verify_token")
    op.drop_column("company_settings", "waha_api_key")
    op.drop_column("company_settings", "waha_session")
    op.drop_column("company_settings", "waha_base_url")
    op.drop_column("company_settings", "evolution_api_key")
    op.drop_column("company_settings", "evolution_base_url")
