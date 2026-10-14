import os
import shutil
import stat
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

SCRIPT = Path("scripts/vps_cleanup.sh").resolve()


def _bash_path() -> str | None:
    git = shutil.which("git")
    if git:
        git_bash = Path(git).resolve().parents[1] / "bin" / "bash.exe"
        if git_bash.is_file():
            return str(git_bash)
    which_bash = shutil.which("bash")
    if which_bash and "system32" not in which_bash.lower():
        return which_bash
    return None


def _bash_path_for_windows(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    drive, tail = os.path.splitdrive(str(path))
    normalized_tail = tail.replace("\\", "/")
    return f"/{drive[0].lower()}{normalized_tail}"


BASH = _bash_path()
BASH_UNAVAILABLE = BASH is None


@pytest.fixture
def test_env_path() -> Path:
    root = Path(".git-bash-test-tmp").resolve()
    path = root / uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        if root.exists() and not any(root.iterdir()):
            root.rmdir()


def _install_stubs(directory: Path) -> Path:
    bin_dir = directory / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    
    # Stub docker
    docker_stub = bin_dir / "docker"
    docker_stub.write_text("#!/bin/sh\necho 'docker stub executed: $@'\nexit 0\n", encoding="utf-8")
    docker_stub.chmod(docker_stub.stat().st_mode | stat.S_IEXEC)
    
    return bin_dir


@pytest.mark.skipif(BASH_UNAVAILABLE, reason="a functional Unix bash is required")
def test_vps_cleanup_script_dry_run_executes_successfully(test_env_path: Path):
    bin_dir = _install_stubs(test_env_path)
    backup_dir = test_env_path / "backups"
    backup_dir.mkdir()
    
    env = {
        **os.environ,
        "BACKUP_DIR": _bash_path_for_windows(backup_dir),
        "LOG_FILE": _bash_path_for_windows(test_env_path / "cleanup.log"),
        "WARN_WAIT_SECONDS": "0",
    }
    
    result = subprocess.run(  # noqa: S603 - the test invokes a fixed local Bash executable.
        [
            BASH,
            "-c",
            'PATH="$1:$PATH"; export PATH; exec "$2" --dry-run',
            "bash",
            _bash_path_for_windows(bin_dir),
            _bash_path_for_windows(SCRIPT),
        ],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    
    assert result.returncode == 0, f"Stderr: {result.stderr}\nStdout: {result.stdout}"
    assert "MODO SIMULAÇÃO (--dry-run) ATIVADO" in result.stdout
    assert "Limpeza concluída com sucesso!" in result.stdout


@pytest.mark.skipif(BASH_UNAVAILABLE, reason="a functional Unix bash is required")
def test_vps_cleanup_script_force_mode_executes_cleaning(test_env_path: Path):
    bin_dir = _install_stubs(test_env_path)
    backup_dir = test_env_path / "backups"
    backup_dir.mkdir()
    
    fake_backup = backup_dir / "agenda_agenda_atende_20200101.sql.gz"
    fake_backup.write_bytes(b"old backup content")
    
    env = {
        **os.environ,
        "BACKUP_DIR": _bash_path_for_windows(backup_dir),
        "LOG_FILE": _bash_path_for_windows(test_env_path / "cleanup.log"),
        "WARN_WAIT_SECONDS": "0",
    }
    
    result = subprocess.run(  # noqa: S603 - the test invokes a fixed local Bash executable.
        [
            BASH,
            "-c",
            'PATH="$1:$PATH"; export PATH; exec "$2" --force',
            "bash",
            _bash_path_for_windows(bin_dir),
            _bash_path_for_windows(SCRIPT),
        ],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    
    assert result.returncode == 0, f"Stderr: {result.stderr}\nStdout: {result.stdout}"
    assert "Iniciando protocolo de manutenção preventiva" in result.stdout
    assert "Limpeza concluída com sucesso!" in result.stdout
