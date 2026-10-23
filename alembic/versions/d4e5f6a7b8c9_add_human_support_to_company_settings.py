"""Add human support contact fields to company_settings.

Revision ID: d4e5f6a7b8c9
Revises: b3c4d5e6f7a8
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "b3c4d5e6f7a8"
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

    if "human_support_phone" not in existing_cols:
        op.add_column(
            "company_settings",
            sa.Column(
                "human_support_phone",
                sa.String(length=20),
                nullable=True,
            ),
        )
    if "human_support_name" not in existing_cols:
        op.add_column(
            "company_settings",
            sa.Column(
                "human_support_name",
                sa.String(length=100),
                nullable=True,
                server_default="Equipe de Atendimento",
            ),
        )
    if "human_support_message" not in existing_cols:
        op.add_column(
            "company_settings",
            sa.Column(
                "human_support_message",
                sa.Text(),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())
    existing_cols = (
        {c["name"] for c in insp.get_columns("company_settings")}
        if "company_settings" in existing_tables
        else set()
    )

    if "human_support_message" in existing_cols:
        op.drop_column("company_settings", "human_support_message")
    if "human_support_name" in existing_cols:
        op.drop_column("company_settings", "human_support_name")
    if "human_support_phone" in existing_cols:
        op.drop_column("company_settings", "human_support_phone")
