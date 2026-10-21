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
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())
    existing_cols = (
        {c["name"] for c in insp.get_columns("company_settings")}
        if "company_settings" in existing_tables
        else set()
    )

    # 1. Adicionar colunas de conexão WhatsApp à tabela company_settings
    columns_to_add = [
        ("evolution_base_url", sa.Column("evolution_base_url", sa.String(length=255), nullable=True)),
        ("evolution_api_key", sa.Column("evolution_api_key", sa.Text(), nullable=True)),
        ("waha_base_url", sa.Column("waha_base_url", sa.String(length=255), nullable=True)),
        ("waha_session", sa.Column("waha_session", sa.String(length=100), nullable=True, server_default="default")),
        ("waha_api_key", sa.Column("waha_api_key", sa.Text(), nullable=True)),
        ("meta_verify_token", sa.Column("meta_verify_token", sa.String(length=100), nullable=True)),
        ("ai_provider", sa.Column("ai_provider", sa.String(length=30), nullable=False, server_default="openai")),
        ("ai_model", sa.Column("ai_model", sa.String(length=100), nullable=False, server_default="gpt-4o-mini")),
        ("ai_api_key", sa.Column("ai_api_key", sa.Text(), nullable=True)),
        ("ai_base_url", sa.Column("ai_base_url", sa.String(length=255), nullable=True)),
        ("ai_temperature", sa.Column("ai_temperature", sa.Numeric(precision=3, scale=2), nullable=False, server_default="0.30")),
        ("ai_system_prompt", sa.Column("ai_system_prompt", sa.Text(), nullable=True)),
    ]

    for col_name, col_def in columns_to_add:
        if col_name not in existing_cols:
            op.add_column("company_settings", col_def)

    # 2. Criar tabela chat_messages para persistir histórico de conversas do WhatsApp
    if "chat_messages" not in existing_tables:
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
    else:
        existing_indices = {i["name"] for i in insp.get_indexes("chat_messages")}
        if "ix_chat_messages_phone" not in existing_indices:
            op.create_index("ix_chat_messages_phone", "chat_messages", ["phone"])
        if "ix_chat_messages_created_at" not in existing_indices:
            op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())
    existing_cols = (
        {c["name"] for c in insp.get_columns("company_settings")}
        if "company_settings" in existing_tables
        else set()
    )

    if "chat_messages" in existing_tables:
        existing_indices = {i["name"] for i in insp.get_indexes("chat_messages")}
        if "ix_chat_messages_created_at" in existing_indices:
            op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
        if "ix_chat_messages_phone" in existing_indices:
            op.drop_index("ix_chat_messages_phone", table_name="chat_messages")
        op.drop_table("chat_messages")

    cols_to_drop = [
        "meta_verify_token",
        "waha_api_key",
        "waha_session",
        "waha_base_url",
        "evolution_api_key",
        "evolution_base_url",
        "ai_system_prompt",
        "ai_temperature",
        "ai_base_url",
        "ai_api_key",
        "ai_model",
        "ai_provider",
    ]
    for col in cols_to_drop:
        if col in existing_cols:
            op.drop_column("company_settings", col)
