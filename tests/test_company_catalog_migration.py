from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.config import settings


def test_company_catalog_migration_consolidates_equal_services_and_preserves_links(
    tmp_path, monkeypatch
):
    """Keeping professional-owned duplicates or breaking references must fail."""
    database_url = f"sqlite:///{(tmp_path / 'company-catalog.db').as_posix()}"
    engine = create_engine(database_url)
    project_root = Path(__file__).resolve().parents[1]
    config = Config()
    config.set_main_option("script_location", str(project_root / "alembic"))
    monkeypatch.setattr(settings, "database_url", database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE professionals (id INTEGER PRIMARY KEY, name VARCHAR(255), active BOOLEAN NOT NULL)"
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE services (
                    id INTEGER PRIMARY KEY,
                    professional_id INTEGER,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    duration_minutes INTEGER,
                    price_cents INTEGER,
                    category VARCHAR(100),
                    active BOOLEAN NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE professional_services (
                    id INTEGER PRIMARY KEY,
                    professional_id INTEGER NOT NULL,
                    service_id INTEGER NOT NULL,
                    price_cents INTEGER NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    commission_percent NUMERIC(5, 2) NOT NULL,
                    active BOOLEAN NOT NULL,
                    created_at DATETIME,
                    updated_at DATETIME,
                    UNIQUE (professional_id, service_id)
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE TABLE appointments (id INTEGER PRIMARY KEY, professional_id INTEGER NOT NULL, service_id INTEGER NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO professionals VALUES (1, 'Ana', 1), (2, 'Bia', 1), (3, 'Clara', 1)"
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO services
                    (id, professional_id, name, description, duration_minutes, price_cents, category, active)
                VALUES
                    (10, 1, 'Corte feminino', 'Corte', 60, 9000, 'Cabelo', 1),
                    (11, 2, 'Corte feminino', 'Corte', 60, 9000, 'Cabelo', 1),
                    (12, 1, ' Corte  feminino ', 'Corte', 60, 9000, 'Cabelo', 1)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO professional_services
                    (id, professional_id, service_id, price_cents, duration_minutes, commission_percent, active)
                VALUES
                    (20, 1, 10, 9000, 60, 10.00, 1),
                    (21, 2, 11, 9000, 60, 25.00, 1),
                    (19, 1, 12, 9000, 60, 15.00, 1),
                    (22, 3, 10, 12000, 90, 30.00, 1)
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO appointments VALUES (30, 1, 10), (31, 2, 11), (32, 1, 12), (33, 3, 10)"
            )
        )

    command.stamp(config, "8d3f6a1c5b7e")
    command.upgrade(config, "9f2a4c6e8b1d")

    columns = {column["name"] for column in inspect(engine).get_columns("services")}
    assignment_columns = {
        column["name"]
        for column in inspect(engine).get_columns("professional_services")
    }
    with engine.connect() as connection:
        services = connection.execute(
            text("SELECT id, price_cents, duration_minutes FROM services")
        ).all()
        assignments = connection.execute(
            text(
                "SELECT professional_id, service_id, commission_percent FROM professional_services ORDER BY professional_id"
            )
        ).all()
        appointment_services = connection.execute(
            text("SELECT service_id FROM appointments ORDER BY id")
        ).scalars().all()

    assert "professional_id" not in columns
    assert {"price_cents", "duration_minutes"}.isdisjoint(assignment_columns)
    assert services == [(10, 9000, 60), (13, 12000, 90)]
    assert [(row[0], row[1]) for row in assignments] == [
        (1, 10),
        (2, 10),
        (3, 13),
    ]
    assert [str(row[2]) for row in assignments] == ["15", "25", "30"]
    assert appointment_services == [10, 10, 10, 13]
