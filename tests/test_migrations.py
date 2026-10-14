import os

import pytest
from sqlalchemy.orm import Session


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL integration database is not configured",
)
def test_postgres_integration_job_uses_postgres(db_session: Session):
    assert db_session.bind.dialect.name == "postgresql"
