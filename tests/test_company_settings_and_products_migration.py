from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from app.database import Base


def test_company_settings_and_products_migration(tmp_path, monkeypatch):
    database_url = f"sqlite:///{(tmp_path / 'settings-products-migration.db').as_posix()}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    project_root = Path(__file__).resolve().parents[1]

    config = Config()
    config.set_main_option("script_location", str(project_root / "alembic"))
    monkeypatch.setattr(settings, "database_url", database_url)

    # Base tables up to previous migration (excluding company_settings and products)
    Base.metadata.create_all(
        engine,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table.name not in {"company_settings", "products"}
        ],
    )
    command.stamp(config, "c7d8e9f0a1b2")

    tables_before = set(inspect(engine).get_table_names())
    assert "company_settings" not in tables_before
    assert "products" not in tables_before

    # Upgrade to new revision
    command.upgrade(config, "d8e9f0a1b2c3")
    tables_after = set(inspect(engine).get_table_names())
    assert "company_settings" in tables_after
    assert "products" in tables_after

    # Test inserting into company_settings
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO company_settings (id, company_name, payment_required, default_gateway, "
                "gateway_credentials, accepted_payment_methods, commission_model, default_commission_rate, "
                "split_enabled, whatsapp_provider, assistant_name, tone, require_cpf, custom_settings) "
                "VALUES (1, 'Test Company', 1, 'asaas', '{}', '[\"pix\"]', 'percentage', 0.0, 0, 'evolution', 'Assistente', 'casual', 0, '{}')"
            )
        )
        row = conn.execute(
            text("SELECT company_name, payment_required, default_gateway FROM company_settings WHERE id = 1")
        ).one()
        assert row[0] == "Test Company"
        assert row[1] == 1
        assert row[2] == "asaas"

    # Test inserting into products
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO products (id, name, price_cents, stock_quantity, active) "
                "VALUES (1, 'Pomada Modeladora', 4500, 10, 1)"
            )
        )
        prod = conn.execute(
            text("SELECT name, price_cents, stock_quantity FROM products WHERE id = 1")
        ).one()
        assert prod[0] == "Pomada Modeladora"
        assert prod[1] == 4500
        assert prod[2] == 10

    # Test downgrade
    command.downgrade(config, "c7d8e9f0a1b2")
    tables_downgraded = set(inspect(engine).get_table_names())
    assert "company_settings" not in tables_downgraded
    assert "products" not in tables_downgraded
