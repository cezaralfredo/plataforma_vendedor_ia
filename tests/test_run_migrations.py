from importlib import util
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess

import pytest


def _load_runner_module():
    path = Path("scripts/run_migrations.py")
    if not path.exists():
        pytest.fail("migration runner module is missing")
    spec = util.spec_from_file_location("run_migrations", path)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migrations_succeed_without_sleeping_on_first_attempt():
    module = _load_runner_module()
    attempts = []
    sleeps = []

    def runner(command, *, check):
        attempts.append((command, check))
        return CompletedProcess(command, 0)

    module.run_migrations(
        max_attempts=3,
        delay_seconds=2,
        runner=runner,
        sleeper=sleeps.append,
    )

    assert attempts == [(["alembic", "upgrade", "head"], True)]
    assert sleeps == []


def test_migrations_retry_a_transient_failure_then_succeed():
    module = _load_runner_module()
    attempts = 0
    sleeps = []

    def runner(command, *, check):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise CalledProcessError(1, command)
        return CompletedProcess(command, 0)

    module.run_migrations(
        max_attempts=3,
        delay_seconds=2,
        runner=runner,
        sleeper=sleeps.append,
    )

    assert attempts == 2
    assert sleeps == [2]


def test_migrations_raise_the_final_failure_after_the_limit():
    module = _load_runner_module()
    attempts = 0
    sleeps = []

    def runner(command, *, check):
        nonlocal attempts
        attempts += 1
        raise CalledProcessError(7, command)

    with pytest.raises(CalledProcessError) as failure:
        module.run_migrations(
            max_attempts=3,
            delay_seconds=2,
            runner=runner,
            sleeper=sleeps.append,
        )

    assert failure.value.returncode == 7
    assert attempts == 3
    assert sleeps == [2, 2]


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"MIGRATION_MAX_ATTEMPTS": "0"}, "MIGRATION_MAX_ATTEMPTS"),
        ({"MIGRATION_MAX_ATTEMPTS": "invalid"}, "MIGRATION_MAX_ATTEMPTS"),
        ({"MIGRATION_RETRY_DELAY_SECONDS": "0"}, "MIGRATION_RETRY_DELAY_SECONDS"),
        ({"MIGRATION_RETRY_DELAY_SECONDS": "nan"}, "MIGRATION_RETRY_DELAY_SECONDS"),
        ({"MIGRATION_RETRY_DELAY_SECONDS": "inf"}, "MIGRATION_RETRY_DELAY_SECONDS"),
        ({"MIGRATION_RETRY_DELAY_SECONDS": "-inf"}, "MIGRATION_RETRY_DELAY_SECONDS"),
    ],
)
def test_invalid_migration_retry_settings_fail_closed(env, message):
    module = _load_runner_module()

    with pytest.raises(ValueError, match=message):
        module.migration_settings_from_env(env)


def test_migration_retry_settings_have_safe_defaults_and_accept_overrides():
    module = _load_runner_module()

    assert module.migration_settings_from_env({}) == (30, 2.0)
    assert module.migration_settings_from_env(
        {
            "MIGRATION_MAX_ATTEMPTS": "5",
            "MIGRATION_RETRY_DELAY_SECONDS": "0.5",
        }
    ) == (5, 0.5)
