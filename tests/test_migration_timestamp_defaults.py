import importlib.util
from pathlib import Path


def _load_harden_schema_migration():
    path = Path("alembic/versions/1c4f5a6b7d8e_harden_schema.py")
    spec = importlib.util.spec_from_file_location("harden_schema_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_harden_schema_sets_database_defaults_for_existing_created_at_columns(monkeypatch):
    migration = _load_harden_schema_migration()
    calls: list[tuple[str, tuple, dict]] = []

    class OperationsRecorder:
        def __getattr__(self, name):
            def record(*args, **kwargs):
                calls.append((name, args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", OperationsRecorder())
    migration.upgrade()

    defaults = {
        args[0]: kwargs["server_default"]
        for name, args, kwargs in calls
        if name == "alter_column" and args[1] == "created_at"
    }

    assert {table: str(default) for table, default in defaults.items()} == {
        "users": "CURRENT_TIMESTAMP",
        "appointments": "CURRENT_TIMESTAMP",
        "payments": "CURRENT_TIMESTAMP",
    }
