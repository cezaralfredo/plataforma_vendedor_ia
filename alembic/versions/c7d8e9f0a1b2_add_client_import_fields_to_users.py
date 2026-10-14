"""Add client import and CRM enrichment fields to users.

Revision ID: c7d8e9f0a1b2
Revises: b5e8a1c3d6f0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b5e8a1c3d6f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
            server_default="direct",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "external_id",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "import_batch_id",
            sa.String(length=50),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "tags",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "custom_fields",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "birth_date",
            sa.Date(),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "gender",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "postal_code",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "city",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "state",
            sa.String(length=2),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "address",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "opt_in_whatsapp",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    op.create_index("ix_users_source", "users", ["source"])
    op.create_index("ix_users_external_id", "users", ["external_id"])
    op.create_index("ix_users_import_batch_id", "users", ["import_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_users_import_batch_id", table_name="users")
    op.drop_index("ix_users_external_id", table_name="users")
    op.drop_index("ix_users_source", table_name="users")

    op.drop_column("users", "opt_in_whatsapp")
    op.drop_column("users", "address")
    op.drop_column("users", "state")
    op.drop_column("users", "city")
    op.drop_column("users", "postal_code")
    op.drop_column("users", "gender")
    op.drop_column("users", "birth_date")
    op.drop_column("users", "custom_fields")
    op.drop_column("users", "notes")
    op.drop_column("users", "tags")
    op.drop_column("users", "import_batch_id")
    op.drop_column("users", "external_id")
    op.drop_column("users", "source")
