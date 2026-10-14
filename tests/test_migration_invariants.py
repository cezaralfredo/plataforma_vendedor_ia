from importlib import util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_invariants_revision():
    path = Path("alembic/versions/4a6f9d2e1b3c_enforce_scheduling_invariants.py")
    spec = util.spec_from_file_location("enforce_scheduling_invariants", path)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_invariants_migration_generates_named_postgresql_exclusion_constraint():
    """Catch an anonymous range expression that Alembic cannot materialize."""
    revision = _load_invariants_revision()
    output = StringIO()
    context = MigrationContext.configure(
        url="postgresql+psycopg://",
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)
    original_operations = revision.op
    revision.op = operations

    try:
        revision.upgrade()
    finally:
        revision.op = original_operations

    ddl = output.getvalue()
    assert "exclude_professional_overlapping_appointments" in ddl
    assert "professional_id WITH =" in ddl
    assert "tstzrange(start_time, end_time, '[)') WITH &&" in ddl
