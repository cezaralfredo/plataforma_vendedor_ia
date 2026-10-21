"""Add coexistence mode fields to company_settings.

Revision ID: a1b2c3d4e5f7
Revises: c3d4e5f6a7b8
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | None = "c3d4e5f6a7b8"
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

    if "coexistence_enabled" not in existing_cols:
        op.add_column(
            "company_settings",
            sa.Column(
                "coexistence_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
    if "coexistence_pause_minutes" not in existing_cols:
        op.add_column(
            "company_settings",
            sa.Column(
                "coexistence_pause_minutes",
                sa.Integer(),
                nullable=False,
                server_default="45",
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

    if "coexistence_pause_minutes" in existing_cols:
        op.drop_column("company_settings", "coexistence_pause_minutes")
    if "coexistence_enabled" in existing_cols:
        op.drop_column("company_settings", "coexistence_enabled")
