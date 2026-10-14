import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, settings
from app.database import Base, get_db
from app.main import create_app

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite://",
)

engine_kwargs = {}
if TEST_DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update(
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
engine = create_engine(TEST_DATABASE_URL, **engine_kwargs)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _test_client(db_session: Session) -> Generator[TestClient, None, None]:
    def _get_test_db():
        try:
            yield db_session
        finally:
            pass

    test_app = create_app(
        Settings(
            admin_username="admin-fixture",
            admin_bootstrap_password="fixture-password-only-123",  # noqa: S106
            admin_session_secret="fixture-session-secret-" + "s" * 32,
        ),
        session_factory=TestingSessionLocal,
    )
    test_app.dependency_overrides[get_db] = _get_test_db
    with TestClient(test_app) as c:
        yield c
    test_app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def anonymous_client(db_session: Session) -> Generator[TestClient, None, None]:
    yield from _test_client(db_session)


@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    for test_client in _test_client(db_session):
        test_client.headers.update({"Authorization": f"Bearer {settings.api_key}"})
        yield test_client
