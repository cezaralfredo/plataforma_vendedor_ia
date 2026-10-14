import gzip
import os
import shutil
import stat
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

SCRIPT = Path("scripts/backup.sh").resolve()


def _bash_path() -> str | None:
    git = shutil.which("git")
    if git:
        git_bash = Path(git).resolve().parents[1] / "bin" / "bash.exe"
        if git_bash.is_file():
            return str(git_bash)
    return shutil.which("bash")


def _bash_path_for_windows(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    drive, tail = os.path.splitdrive(str(path))
    normalized_tail = tail.replace("\\", "/")
    return f"/{drive[0].lower()}{normalized_tail}"


BASH = _bash_path()
BASH_UNAVAILABLE = BASH is None


@pytest.fixture
def git_bash_tmp_path() -> Path:
    root = Path(".git-bash-test-tmp").resolve()
    path = root / uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        root.rmdir()


def _install_stub(directory: Path, body: str) -> Path:
    directory.mkdir()
    path = directory / "pg_dump"
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return directory


def _run_backup(tmp_path: Path, bin_dir: Path):
    assert BASH is not None
    env = {
        **os.environ,
        "BACKUP_DIR": _bash_path_for_windows(tmp_path),
        "POSTGRES_PASSWORD": "secret",
        "BACKUP_RETENTION_DAYS": "30",
    }
    env.pop("BACKUP_SCHEDULE", None)
    return subprocess.run(  # noqa: S603
        [
            BASH,
            "-c",
            'PATH="$1:$PATH"; export PATH; exec "$2"',
            "bash",
            _bash_path_for_windows(bin_dir),
            _bash_path_for_windows(SCRIPT),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(BASH_UNAVAILABLE, reason="a functional Unix bash is required")
def test_failed_dump_does_not_publish_backup(git_bash_tmp_path: Path):
    tmp_path = git_bash_tmp_path
    bin_dir = _install_stub(
        tmp_path / "bin", "#!/bin/sh\nprintf '%s\\n' 'pg_dump failed' >&2\nexit 2\n"
    )
    result = _run_backup(tmp_path, bin_dir)
    assert "pg_dump failed" in result.stderr
    assert result.returncode != 0
    assert list(tmp_path.glob("*.sql.gz")) == []


@pytest.mark.skipif(BASH_UNAVAILABLE, reason="a functional Unix bash is required")
def test_env_password_creates_valid_nonempty_gzip(git_bash_tmp_path: Path):
    tmp_path = git_bash_tmp_path
    bin_dir = _install_stub(
        tmp_path / "bin",
        "#!/bin/sh\nprintf '%s\\n' 'CREATE TABLE ok();'\n",
    )
    result = _run_backup(tmp_path, bin_dir)
    assert result.returncode == 0, result.stderr
    backups = list(tmp_path.glob("agenda_agenda_atende_*.sql.gz"))
    assert len(backups) == 1
    assert gzip.decompress(backups[0].read_bytes()).startswith(b"CREATE TABLE")
