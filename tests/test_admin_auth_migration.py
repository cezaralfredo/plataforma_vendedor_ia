from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import Settings, settings
from app.database import Base
from app.main import create_app
from app.models.admin_account import AdminAccount


def test_admin_migration_upgrade_restart_and_downgrade_on_sqlite(tmp_path, monkeypatch):
    database_url = f"sqlite:///{(tmp_path / 'admin-migration.db').as_posix()}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    project_root = Path(__file__).resolve().parents[1]
    # Keep the application's Alembic logging configuration from disabling pytest's
    # captured loggers when the migration runs in this same process.
    config = Config()
    config.set_main_option("script_location", str(project_root / "alembic"))
    monkeypatch.setattr(settings, "database_url", database_url)

    try:
        # Earlier migrations contain PostgreSQL-only DDL. Build their equivalent
        # schema, then execute this task's actual migration through Alembic.
        Base.metadata.create_all(
            engine,
            tables=[table for table in Base.metadata.sorted_tables if table.name != "admin_accounts"],
        )
        command.stamp(config, "7e1c3a9d4b6f")
        original_tables = set(inspect(engine).get_table_names())
        command.upgrade(config, "8d3f6a1c5b7e")
        command.upgrade(config, "8d3f6a1c5b7e")
        assert set(inspect(engine).get_table_names()) == original_tables | {"admin_accounts"}

        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO admin_accounts (id, username, password_hash) VALUES (1, 'fixture', 'hash-fixture')"
            ))
            assert connection.execute(text(
                "SELECT auth_version, failed_login_count FROM admin_accounts"
            )).one() == (1, 0)

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO admin_accounts (id, username, password_hash) VALUES (2, 'other', 'hash-fixture')"
            ))
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM admin_accounts WHERE id = 1"))

        factory = sessionmaker(bind=engine)
        initial = Settings(
            admin_username="migration-admin",
            admin_bootstrap_password="migration-password-123",  # noqa: S106
        )
        with TestClient(create_app(initial, session_factory=factory)):
            pass
        with TestClient(create_app(Settings(admin_bootstrap_password=""), session_factory=factory)):
            pass
        with Session(engine) as session:
            assert session.get(AdminAccount, 1).username == "migration-admin"
            assert session.query(AdminAccount).count() == 1

        command.downgrade(config, "7e1c3a9d4b6f")
        assert set(inspect(engine).get_table_names()) == original_tables
    finally:
        engine.dispose()
