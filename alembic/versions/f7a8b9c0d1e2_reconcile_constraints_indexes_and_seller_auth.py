"""reconcile indexes, delivery fk restrict, and seller auth columns

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-11-21 11:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. Colunas de segurança e revogação de sessão em sellers
    if "sellers" in tables:
        if not _has_column(inspector, "sellers", "auth_version"):
            op.add_column(
                "sellers",
                sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"),
            )
        if not _has_column(inspector, "sellers", "failed_login_count"):
            op.add_column(
                "sellers",
                sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
            )
        if not _has_column(inspector, "sellers", "locked_until"):
            op.add_column(
                "sellers",
                sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            )

    # 2. Índices de alta frequência ausentes
    if "deliveries" in tables:
        for idx_name, cols in (
            ("ix_deliveries_delivery_status", ["delivery_status"]),
            ("ix_deliveries_payment_status", ["payment_status"]),
            ("ix_deliveries_payment_timing", ["payment_timing"]),
            ("ix_deliveries_created_at", ["created_at"]),
        ):
            if not _has_index(inspector, "deliveries", idx_name):
                op.create_index(idx_name, "deliveries", cols)

        # Troca FK deliveries.user_id de ON DELETE CASCADE para ON DELETE RESTRICT no PostgreSQL
        if bind.dialect.name == "postgresql":
            for fk in inspector.get_foreign_keys("deliveries"):
                if fk.get("constrained_columns") == ["user_id"] and fk.get("name"):
                    op.drop_constraint(fk["name"], "deliveries", type_="foreignkey")
                    op.create_foreign_key(
                        "fk_deliveries_user_id_users",
                        "deliveries",
                        "users",
                        ["user_id"],
                        ["id"],
                        ondelete="RESTRICT",
                    )
                    break

    if "chat_messages" in tables and not _has_index(
        inspector, "chat_messages", "ix_chat_messages_phone_created_at"
    ):
        op.create_index(
            "ix_chat_messages_phone_created_at",
            "chat_messages",
            ["phone", "created_at"],
        )

    if "notification_deliveries" in tables and not _has_index(
        inspector, "notification_deliveries", "ix_notification_deliveries_status_next_attempt"
    ):
        op.create_index(
            "ix_notification_deliveries_status_next_attempt",
            "notification_deliveries",
            ["status", "next_attempt_at"],
        )

    if "payments" in tables:
        for idx_name, cols in (
            ("ix_payments_seller_status", ["seller_id", "status"]),
            ("ix_payments_branch_status", ["branch_id", "status"]),
            ("ix_payments_created_at", ["created_at"]),
        ):
            if not _has_index(inspector, "payments", idx_name):
                op.create_index(idx_name, "payments", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "payments" in tables:
        for idx_name in (
            "ix_payments_created_at",
            "ix_payments_branch_status",
            "ix_payments_seller_status",
        ):
            if _has_index(inspector, "payments", idx_name):
                op.drop_index(idx_name, table_name="payments")

    if "notification_deliveries" in tables and _has_index(
        inspector, "notification_deliveries", "ix_notification_deliveries_status_next_attempt"
    ):
        op.drop_index(
            "ix_notification_deliveries_status_next_attempt",
            table_name="notification_deliveries",
        )

    if "chat_messages" in tables and _has_index(
        inspector, "chat_messages", "ix_chat_messages_phone_created_at"
    ):
        op.drop_index("ix_chat_messages_phone_created_at", table_name="chat_messages")

    if "deliveries" in tables:
        for idx_name in (
            "ix_deliveries_created_at",
            "ix_deliveries_payment_timing",
            "ix_deliveries_payment_status",
            "ix_deliveries_delivery_status",
        ):
            if _has_index(inspector, "deliveries", idx_name):
                op.drop_index(idx_name, table_name="deliveries")

    if "sellers" in tables:
        for col_name in ("locked_until", "failed_login_count", "auth_version"):
            if _has_column(inspector, "sellers", col_name):
                op.drop_column("sellers", col_name)
