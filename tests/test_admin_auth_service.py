from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app import main as main_module
from app.admin.auth_service import (
    authenticate_admin,
    bootstrap_admin_account,
    change_admin_password,
    hash_password,
    record_failed_login,
    verify_password,
)
from app.config import Settings
from app.models.admin_account import AdminAccount


@pytest.fixture
def admin_settings() -> Settings:
    return Settings(
        admin_username="admin-fixture",
        admin_bootstrap_password="fixture-password-only-123",  # noqa: S106
    )


def test_hash_does_not_expose_password_and_verifies_only_the_original_value():
    password = "fixture-password-only-123"  # noqa: S105

    encoded_hash = hash_password(password)

    assert password not in encoded_hash
    assert verify_password(password, encoded_hash)
    assert not verify_password("wrong-fixture-password", encoded_hash)


def test_bootstrap_creates_the_single_account_once(
    db_session: Session, admin_settings: Settings
):
    first_account = bootstrap_admin_account(db_session, admin_settings)
    second_account = bootstrap_admin_account(db_session, admin_settings)

    assert first_account.id == 1
    assert second_account.id == first_account.id
    assert first_account.username == "admin-fixture"
    assert db_session.query(type(first_account)).count() == 1


def test_five_failed_logins_lock_the_account_for_fifteen_minutes(
    db_session: Session, admin_settings: Settings
):
    account = bootstrap_admin_account(db_session, admin_settings)
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    for _ in range(5):
        assert authenticate_admin(
            db_session,
            account.username,
            "wrong-fixture-password",
            now,
        ) is None

    db_session.refresh(account)
    assert account.failed_login_count == 5
    assert account.locked_until is not None
    assert account.locked_until.replace(tzinfo=UTC) == now + timedelta(minutes=15)

    db_session.expire_all()
    assert authenticate_admin(
        db_session,
        account.username,
        "wrong-fixture-password",
        now,
    ) is None


def test_record_failed_login_sets_the_lock_on_the_fifth_attempt(
    db_session: Session, admin_settings: Settings
):
    account = bootstrap_admin_account(db_session, admin_settings)
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    for _ in range(5):
        record_failed_login(account, now)

    assert account.failed_login_count == 5
    assert account.locked_until == now + timedelta(minutes=15)


def test_bootstrap_requires_a_password_only_before_the_account_exists(
    db_session: Session, admin_settings: Settings
):
    missing_password_settings = Settings(admin_username="admin-fixture")

    with pytest.raises(RuntimeError, match="has not been initialized"):
        bootstrap_admin_account(db_session, missing_password_settings)

    created = bootstrap_admin_account(db_session, admin_settings)
    reused = bootstrap_admin_account(db_session, missing_password_settings)

    assert reused.id == created.id


def test_successful_authentication_clears_failures_and_password_change_revokes_sessions(
    db_session: Session, admin_settings: Settings
):
    account = bootstrap_admin_account(db_session, admin_settings)
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    record_failed_login(account, now)
    db_session.commit()

    authenticated = authenticate_admin(
        db_session, account.username, "fixture-password-only-123", now
    )
    assert authenticated is not None
    assert authenticated.failed_login_count == 0
    assert authenticated.locked_until is None

    change_admin_password(db_session, authenticated, "new-fixture-password-456")

    assert authenticated.auth_version == 2
    assert verify_password("new-fixture-password-456", authenticated.password_hash)


def test_production_settings_error_does_not_render_the_rejected_secret():
    rejected_secret = "fixture-short-secret"  # noqa: S105

    with pytest.raises(ValidationError) as failure:
        Settings(
            debug=False,
            api_key="a" * 32,
            admin_api_key="b" * 32,
            asaas_webhook_token="c" * 32,
            admin_session_secret=rejected_secret,
            admin_recovery_key="d" * 32,
        )

    assert rejected_secret not in str(failure.value)


def test_production_rejects_bootstrap_password_placeholder_without_rendering_it():
    placeholder = "admin-bootstrap-password-change-me"

    with pytest.raises(ValidationError) as failure:
        Settings(
            debug=False,
            api_key="a" * 32,
            admin_api_key="b" * 32,
            asaas_webhook_token="c" * 32,
            admin_bootstrap_password=placeholder,
            admin_session_secret="d" * 32,
            admin_recovery_key="e" * 32,
        )

    assert placeholder not in str(failure.value)


def test_startup_bootstraps_the_injected_database_and_allows_a_restart_without_password(
    db_session: Session, admin_settings: Settings, monkeypatch
):
    def reject_global_connection(*args, **kwargs):
        pytest.fail("Startup attempted to connect to the global database")

    monkeypatch.setattr(main_module.SessionLocal.kw["bind"], "connect", reject_global_connection)
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.bind,
    )
    first_app = main_module.create_app(
        admin_settings,
        session_factory=session_factory,
    )

    with TestClient(first_app):
        pass

    created = db_session.get(AdminAccount, 1)
    assert created.username == "admin-fixture"
    assert verify_password("fixture-password-only-123", created.password_hash)
    original_hash = created.password_hash

    restart_settings = Settings(admin_username="admin-fixture")
    restarted_app = main_module.create_app(
        restart_settings,
        session_factory=session_factory,
    )

    with TestClient(restarted_app):
        pass

    db_session.refresh(created)
    assert created.password_hash == original_hash
    assert db_session.query(AdminAccount).count() == 1


def test_separate_sessions_accumulate_failed_logins_without_losing_state(
    db_session: Session, admin_settings: Settings
):
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.bind,
    )
    account = bootstrap_admin_account(db_session, admin_settings)
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    for _ in range(2):
        worker_session = session_factory()
        try:
            assert authenticate_admin(
                worker_session,
                account.username,
                "wrong-fixture-password",
                now,
            ) is None
        finally:
            worker_session.close()

    db_session.refresh(account)
    assert account.failed_login_count == 2


@pytest.mark.parametrize(
    ("invalid_field", "invalid_value"),
    [
        ("api_key", "short-api"),
        ("admin_api_key", "short-admin"),
        ("asaas_webhook_token", "short-webhook"),
        ("admin_username", " "),
        ("admin_bootstrap_password", "short-pass"),
        ("admin_session_secret", "short-session"),
        ("admin_recovery_key", "short-recovery"),
        ("debug", "invalid-bool"),
    ],
)
def test_configuration_errors_hide_all_supplied_secrets(invalid_field, invalid_value):
    values = {
        "debug": False,
        "api_key": "api-fixture-" + "a" * 32,
        "admin_api_key": "admin-fixture-" + "b" * 32,
        "asaas_webhook_token": "webhook-fixture-" + "c" * 32,
        "admin_bootstrap_password": "bootstrap-fixture-password-123",
        "admin_session_secret": "session-fixture-" + "d" * 32,
        "admin_recovery_key": "recovery-fixture-" + "e" * 32,
        "asaas_api_key": "asaas-fixture-" + "f" * 32,
        "database_url": "postgresql://fixture:database-password@localhost/test",
    }
    values[invalid_field] = invalid_value

    with pytest.raises(ValidationError) as failure:
        Settings(**values)

    rendered = str(failure.value) + repr(failure.value)
    for field, value in values.items():
        if field not in {"debug", "admin_username"}:
            assert value not in rendered


def test_authentication_refreshes_previously_loaded_failure_count(
    db_session: Session, admin_settings: Settings
):
    account = bootstrap_admin_account(db_session, admin_settings)
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    with Session(db_session.bind) as worker:
        for _ in range(4):
            authenticate_admin(worker, account.username, "wrong-password", now)

    assert authenticate_admin(db_session, account.username, "wrong-password", now) is None
    db_session.refresh(account)
    assert account.failed_login_count == 5
    assert account.locked_until.replace(tzinfo=UTC) == now + timedelta(minutes=15)


def test_password_changes_increment_the_persisted_version_from_a_stale_account(
    db_session: Session, admin_settings: Settings
):
    account = bootstrap_admin_account(db_session, admin_settings)
    with Session(db_session.bind) as worker:
        worker_account = worker.get(AdminAccount, 1)
        change_admin_password(worker, worker_account, "first-new-password-123")

    change_admin_password(db_session, account, "second-new-password-456")

    assert account.auth_version == 3
    assert verify_password("second-new-password-456", account.password_hash)


def test_bootstrap_recovers_from_a_competing_insert_without_overwriting_it(
    db_session: Session, admin_settings: Settings, monkeypatch
):
    original_scalar = db_session.scalar
    first_read = True

    def scalar_with_competing_bootstrap(*args, **kwargs):
        nonlocal first_read
        result = original_scalar(*args, **kwargs)
        if first_read:
            first_read = False
            assert result is None
            with Session(db_session.bind) as worker:
                bootstrap_admin_account(
                    worker,
                    Settings(
                        admin_username="winning-admin",
                        admin_bootstrap_password="winning-password-123",  # noqa: S106
                    ),
                )
        return result

    monkeypatch.setattr(db_session, "scalar", scalar_with_competing_bootstrap)
    account = bootstrap_admin_account(db_session, admin_settings)

    assert account.username == "winning-admin"
    assert verify_password("winning-password-123", account.password_hash)
    assert db_session.query(AdminAccount).count() == 1
    account.failed_login_count = 2
    db_session.commit()
    db_session.refresh(account)
    assert account.failed_login_count == 2


@pytest.mark.postgres
def test_postgres_parallel_failed_logins_reach_the_lock_threshold(
    db_session: Session, admin_settings: Settings
):
    if db_session.bind.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    bootstrap_admin_account(db_session, admin_settings)
    barrier = Barrier(5, timeout=10)
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    def fail_login(_):
        with Session(db_session.bind) as worker:
            # Load before any worker updates, exercising each session's identity map.
            account = worker.get(AdminAccount, 1)
            barrier.wait()
            return authenticate_admin(worker, account.username, "wrong-password", now)

    with ThreadPoolExecutor(max_workers=5) as executor:
        assert list(executor.map(fail_login, range(5))) == [None] * 5

    db_session.expire_all()
    account = db_session.get(AdminAccount, 1)
    assert account.failed_login_count == 5
    assert account.locked_until == now + timedelta(minutes=15)


@pytest.mark.postgres
def test_postgres_parallel_password_changes_preserve_both_version_increments(
    db_session: Session, admin_settings: Settings
):
    if db_session.bind.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    bootstrap_admin_account(db_session, admin_settings)
    barrier = Barrier(2, timeout=10)

    def change_password(index):
        with Session(db_session.bind) as worker:
            account = worker.get(AdminAccount, 1)
            barrier.wait()
            change_admin_password(worker, account, f"new-fixture-password-{index}")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(change_password, range(2)))

    db_session.expire_all()
    assert db_session.get(AdminAccount, 1).auth_version == 3
