from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from math import isfinite
from subprocess import CompletedProcess

CommandRunner = Callable[..., CompletedProcess[str]]
Sleeper = Callable[[float], None]


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def migration_settings_from_env(env: Mapping[str, str]) -> tuple[int, float]:
    return (
        _positive_int(env, "MIGRATION_MAX_ATTEMPTS", 30),
        _positive_float(env, "MIGRATION_RETRY_DELAY_SECONDS", 2),
    )


def run_migrations(
    *,
    max_attempts: int,
    delay_seconds: float,
    runner: CommandRunner = subprocess.run,
    sleeper: Sleeper = time.sleep,
) -> None:
    command: Sequence[str] = ["alembic", "upgrade", "head"]
    for attempt in range(1, max_attempts + 1):
        try:
            runner(list(command), check=True)
            print("Database migrations completed")
            return
        except subprocess.CalledProcessError:
            if attempt == max_attempts:
                print(f"Database migrations failed after {attempt} attempts")
                raise
            print(
                f"Database migration attempt {attempt}/{max_attempts} failed; "
                f"retrying in {delay_seconds:g}s"
            )
            sleeper(delay_seconds)


def main() -> None:
    max_attempts, delay_seconds = migration_settings_from_env(os.environ)
    run_migrations(
        max_attempts=max_attempts,
        delay_seconds=delay_seconds,
    )


if __name__ == "__main__":
    main()
