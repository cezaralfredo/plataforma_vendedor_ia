# Controlled Portainer Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the hidden local-PostgreSQL startup dependency, make Pull Requests validate the complete artifact, and provide a controlled immutable deployment definition for Portainer with Neon.

**Architecture:** A testable Python migration runner retries Alembic against the configured `DATABASE_URL`; the shell entrypoint becomes thin wiring. GitHub Actions tests PostgreSQL behavior and builds images on Pull Requests, while production deployment becomes an explicit Portainer operation using a commit tag. A dedicated Neon Compose file matches the live topology without embedding the database credential in YAML.

**Tech Stack:** Python 3.11, Pytest, Alembic, SQLAlchemy, Psycopg 3, Bash, GitHub Actions, Docker Buildx, Docker Compose, Portainer CE, Neon PostgreSQL, Nginx Proxy Manager.

**Spec:** `docs/superpowers/specs/2026-08-24-controlled-portainer-deployment-design.md`

## Global Constraints

- Do not modify, restart, recreate, or delete anything in the live Portainer environment.
- Do not merge Pull Request #1.
- Do not rotate, print, persist, or commit any production credential.
- Keep the existing local PostgreSQL container and volume untouched.
- Use `postgresql+psycopg://` for every repository-owned PostgreSQL SQLAlchemy URL.
- Production artifacts must be deployable by a commit-derived `IMAGE_TAG`; `latest` remains publication compatibility only.
- Docker is unavailable locally, so Linux image construction must pass in GitHub Actions before merge.
- Executable behavior changes follow red-green-refactor. YAML and Compose changes use structural tests approved as the configuration-file exception.

---

### Task 1: Retry migrations against the configured database

**Files:**
- Create: `scripts/run_migrations.py`
- Create: `tests/test_run_migrations.py`
- Modify: `entrypoint.sh`
- Modify: `tests/test_deployment_config.py`

**Interfaces:**
- Produces: `run_migrations(*, max_attempts: int, delay_seconds: float, runner: CommandRunner = subprocess.run, sleeper: Sleeper = time.sleep) -> None`.
- Produces: `migration_settings_from_env(env: Mapping[str, str]) -> tuple[int, float]`.
- Consumes: `MIGRATION_MAX_ATTEMPTS`, default `30`; `MIGRATION_RETRY_DELAY_SECONDS`, default `2`.
- Entrypoint consumes: `/app/scripts/run_migrations.py` and the existing `DATABASE_URL`/`*_FILE` contract.

- [ ] **Step 1: Write failing migration-runner behavior tests**

Create `tests/test_run_migrations.py` with a loader that fails inside the test when the new module does not exist, allowing the first red run to report the missing behavior rather than fail collection:

```python
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
```

- [ ] **Step 2: Run the new tests and verify the expected red state**

Run:

```powershell
pytest tests/test_run_migrations.py -q
```

Expected: FAIL with `migration runner module is missing`.

- [ ] **Step 3: Implement the minimal migration runner**

Create `scripts/run_migrations.py`:

```python
from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
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
    if value <= 0:
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
```

- [ ] **Step 4: Run the migration-runner tests and verify green**

Run:

```powershell
pytest tests/test_run_migrations.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Add a failing entrypoint wiring invariant**

Append to `tests/test_deployment_config.py`:

```python
def test_runtime_entrypoint_uses_configured_database_for_migrations():
    entrypoint = Path("entrypoint.sh").read_text(encoding="utf-8")
    assert "pg_isready -h postgres" not in entrypoint
    assert "python /app/scripts/run_migrations.py" in entrypoint
    assert "DATABASE_URL" in entrypoint.split("for secret in", 1)[1].split("; do", 1)[0]
```

This is a thin wiring invariant; retry behavior remains covered through the executable Python runner.

- [ ] **Step 6: Run the entrypoint test and verify the expected red state**

Run:

```powershell
pytest tests/test_deployment_config.py::test_runtime_entrypoint_uses_configured_database_for_migrations -q
```

Expected: FAIL because `entrypoint.sh` still contains `pg_isready -h postgres` and does not invoke the runner.

- [ ] **Step 7: Rewire the runtime entrypoint**

In `entrypoint.sh`, include `DATABASE_URL` in the secret-loading loop, remove the fixed `pg_isready` loop, and replace the direct migration command with:

```bash
echo "🔄 Executando migrações Alembic..."
python /app/scripts/run_migrations.py
echo "✅ Migrações aplicadas"
```

Keep placeholder substitution for `POSTGRES_PASSWORD` and keep the final Uvicorn `exec` unchanged.

- [ ] **Step 8: Verify the task and commit**

Run:

```powershell
pytest tests/test_run_migrations.py tests/test_deployment_config.py -q
ruff check scripts/run_migrations.py tests/test_run_migrations.py tests/test_deployment_config.py
python -m compileall -q scripts/run_migrations.py
```

If Bash is available, also run:

```bash
bash -n entrypoint.sh
```

Expected: every command exits `0`.

Commit:

```powershell
git add scripts/run_migrations.py entrypoint.sh tests/test_run_migrations.py tests/test_deployment_config.py
git commit -m "fix: decouple migrations from local postgres"
```

---

### Task 2: Make Pull Requests validate tests and container images

**Files:**
- Create: `requirements-dev.txt`
- Modify: `.github/workflows/ci-cd.yml`
- Modify: `tests/test_deployment_config.py`

**Interfaces:**
- Consumes: `requirements-dev.txt` as the declared local/CI validation tool set.
- Produces workflow job: `test`, required before all builds.
- Produces workflow job: `validate-images`, Pull Request-only, non-publishing Linux/AMD64 builds.
- Produces workflow job: `build`, `master`/tag/manual-only publishing of multi-architecture runtime and backup images.

- [ ] **Step 1: Add semantic YAML helpers and failing workflow tests**

Add `import yaml` and this helper to `tests/test_deployment_config.py`:

```python
def _yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)
```

Add these tests:

```python
def test_ci_uses_psycopg3_urls_for_migrations_and_tests():
    jobs = _yaml(".github/workflows/ci-cd.yml")["jobs"]
    migration = _step(jobs["test"], "Run Alembic migrations")
    tests = _step(jobs["test"], "Run tests with coverage")
    expected = "postgresql+psycopg://test:test@localhost:5432/test_db"
    assert migration["env"]["DATABASE_URL"] == expected
    assert tests["env"]["DATABASE_URL"] == expected
    assert tests["env"]["TEST_DATABASE_URL"] == expected


def test_pull_requests_build_both_images_without_publishing():
    jobs = _yaml(".github/workflows/ci-cd.yml")["jobs"]
    validation = jobs["validate-images"]
    assert validation["needs"] == "test"
    assert "pull_request" in validation["if"]
    builds = [
        step
        for step in validation["steps"]
        if step.get("uses", "").startswith("docker/build-push-action@")
    ]
    assert len(builds) == 2
    assert {step["with"]["file"] for step in builds} == {
        "./Dockerfile",
        "./Dockerfile.backup",
    }
    assert all(step["with"]["push"] is False for step in builds)


def test_ci_does_not_claim_an_automatic_production_deploy():
    jobs = _yaml(".github/workflows/ci-cd.yml")["jobs"]
    assert "deploy" not in jobs
    assert jobs["build"]["needs"] == "test"
```

- [ ] **Step 2: Run the workflow tests and verify the expected red state**

Run:

```powershell
pytest tests/test_deployment_config.py -q
```

Expected: FAIL for the legacy URL, missing `validate-images`, and existing `deploy` job.

- [ ] **Step 3: Declare the development toolchain**

Create `requirements-dev.txt`:

```text
-r requirements.txt
pytest-cov==7.1.0
ruff==0.16.3
mypy==1.17.1
PyYAML==6.0.3
```

Use versions compatible with Python 3.11 and the versions already validated in this workspace. If the installed Pytest coverage or Ruff version differs, resolve the version from the current environment before committing rather than weakening the pin.

- [ ] **Step 4: Correct the test job**

In `.github/workflows/ci-cd.yml`:

- replace the two install commands with `pip install -r requirements-dev.txt`;
- set both `DATABASE_URL` values and `TEST_DATABASE_URL` to `postgresql+psycopg://test:test@localhost:5432/test_db`;
- keep Ruff and MyPy blocking;
- keep the PostgreSQL service and coverage threshold unchanged.

- [ ] **Step 5: Add non-publishing Pull Request image builds**

Add this job after `test`:

```yaml
  validate-images:
    name: Validate container images
    needs: test
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build runtime image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./Dockerfile
          target: runtime
          push: false
          platforms: linux/amd64
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Build backup image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./Dockerfile.backup
          push: false
          platforms: linux/amd64
```

- [ ] **Step 6: Remove the misleading automatic deploy job**

Delete the complete `deploy` job. Keep the existing `build` job dependent on `test`, publishing runtime and backup images only for push/manual events. Preserve the commit-derived metadata tag and `latest` compatibility tag.

- [ ] **Step 7: Verify the workflow structure and commit**

Run:

```powershell
pytest tests/test_deployment_config.py -q
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci-cd.yml', encoding='utf-8')); print('workflow yaml ok')"
ruff check tests/test_deployment_config.py
```

Expected: all commands exit `0`.

Commit:

```powershell
git add requirements-dev.txt .github/workflows/ci-cd.yml tests/test_deployment_config.py
git commit -m "ci: validate pull requests before publishing"
```

---

### Task 3: Add the immutable Portainer + Neon deployment definition

**Files:**
- Create: `docker-compose.portainer-neon.yml`
- Create: `DEPLOY_PORTAINER_NEON.md`
- Modify: `DEPLOY_PORTAINER_NPM.md`
- Modify: `README.md`
- Modify: `tests/test_deployment_config.py`

**Interfaces:**
- Consumes required stack variables: `IMAGE_TAG`, `DATABASE_URL`, `API_KEY`, `ADMIN_API_KEY`, `ASAAS_API_KEY`, `ASAAS_WEBHOOK_TOKEN`.
- Consumes optional stack variables: `REGISTRY`, `GITHUB_REPOSITORY`, `APP_NAME`, `APP_TIMEZONE`, `ASAAS_BASE_URL`, `NPM_NETWORK`.
- Produces Nginx Proxy Manager alias: `agenda-api` on the external `npm` network.

- [ ] **Step 1: Write failing structural tests for the Neon stack**

Add to `tests/test_deployment_config.py`:

```python
def test_portainer_neon_stack_has_only_the_external_database_api():
    compose = _yaml("docker-compose.portainer-neon.yml")
    assert set(compose["services"]) == {"api"}
    assert "volumes" not in compose


def test_portainer_neon_stack_requires_traceable_image_and_database_config():
    compose = _yaml("docker-compose.portainer-neon.yml")
    api = compose["services"]["api"]
    environment = api["environment"]
    assert "${IMAGE_TAG:?Defina IMAGE_TAG no Portainer}" in api["image"]
    assert environment["DATABASE_URL"] == (
        "${DATABASE_URL:?Defina DATABASE_URL no Portainer}"
    )
    assert environment["APP_TIMEZONE"] == "${APP_TIMEZONE:-America/Sao_Paulo}"
    assert environment["DEBUG"] == "false"

    source = Path("docker-compose.portainer-neon.yml").read_text(encoding="utf-8")
    assert "postgresql://" not in source
    assert "postgresql+psycopg://" not in source
    assert ":latest" not in api["image"]


def test_portainer_neon_stack_uses_only_the_existing_proxy_network():
    compose = _yaml("docker-compose.portainer-neon.yml")
    api = compose["services"]["api"]
    assert set(api["networks"]) == {"npm"}
    assert api["networks"]["npm"]["aliases"] == ["agenda-api"]
    assert "ports" not in api
    assert compose["networks"]["npm"] == {
        "external": True,
        "name": "${NPM_NETWORK:-nginx-proxy_default}",
    }
```

- [ ] **Step 2: Run the Neon stack tests and verify the expected red state**

Run:

```powershell
pytest tests/test_deployment_config.py -q
```

Expected: FAIL because `docker-compose.portainer-neon.yml` does not exist.

- [ ] **Step 3: Create the dedicated Compose definition**

Create `docker-compose.portainer-neon.yml`:

```yaml
# Portainer CE + Nginx Proxy Manager + Neon PostgreSQL.
# Define all required values in the Portainer Stack environment table.
services:
  api:
    image: "${REGISTRY:-ghcr.io}/${GITHUB_REPOSITORY:-cezaralfredo/plataforma_atende_agenda}:${IMAGE_TAG:?Defina IMAGE_TAG no Portainer}"
    restart: unless-stopped
    environment:
      DATABASE_URL: "${DATABASE_URL:?Defina DATABASE_URL no Portainer}"
      API_KEY: "${API_KEY:?Defina API_KEY no Portainer}"
      ADMIN_API_KEY: "${ADMIN_API_KEY:?Defina ADMIN_API_KEY no Portainer}"
      APP_NAME: "${APP_NAME:-Agenda Atende}"
      APP_TIMEZONE: "${APP_TIMEZONE:-America/Sao_Paulo}"
      DEBUG: "false"
      ASAAS_API_KEY: "${ASAAS_API_KEY:?Defina ASAAS_API_KEY no Portainer}"
      ASAAS_BASE_URL: "${ASAAS_BASE_URL:-https://api.asaas.com/v3}"
      ASAAS_WEBHOOK_TOKEN: "${ASAAS_WEBHOOK_TOKEN:?Defina ASAAS_WEBHOOK_TOKEN no Portainer}"
    expose:
      - "8000"
    networks:
      npm:
        aliases:
          - agenda-api

networks:
  npm:
    external: true
    name: "${NPM_NETWORK:-nginx-proxy_default}"
```

- [ ] **Step 4: Document the controlled Neon deployment**

Create `DEPLOY_PORTAINER_NEON.md` with these exact operational gates:

- use `docker-compose.portainer-neon.yml` only for the external Neon topology;
- obtain `IMAGE_TAG` from the successful `master` image build;
- verify a Neon backup/restore point before changing the stack;
- create a replacement credential first and keep the previous credential valid during rollout;
- enter `DATABASE_URL` in Portainer's environment table, never inline in the Compose editor;
- state that Docker Standalone environment values remain visible to Portainer administrators and container inspection;
- validate `/ready`, migrations, API authentication, MCP, payments, and webhooks;
- rollback by restoring the previous image tag and stack configuration;
- prohibit removing the old PostgreSQL volume during this rollout.

Update `DEPLOY_PORTAINER_NPM.md` to identify its existing Compose as the local-PostgreSQL variant and link to the Neon guide. Add both deployment variants to the README deployment section.

- [ ] **Step 5: Verify the deployment definition and commit**

Run:

```powershell
pytest tests/test_deployment_config.py -q
python -c "import yaml; yaml.safe_load(open('docker-compose.portainer-neon.yml', encoding='utf-8')); print('compose yaml ok')"
ruff check tests/test_deployment_config.py
git diff --check
```

Expected: all commands exit `0`.

Commit:

```powershell
git add docker-compose.portainer-neon.yml DEPLOY_PORTAINER_NEON.md DEPLOY_PORTAINER_NPM.md README.md tests/test_deployment_config.py
git commit -m "docs: add controlled Neon Portainer deployment"
```

---

### Task 4: Run complete local verification

**Files:**
- Verify only; modify a file only to correct a discovered regression through a new red-green cycle.

**Interfaces:**
- Consumes all deliverables from Tasks 1–3.
- Produces fresh local evidence required before pushing the branch.

- [ ] **Step 1: Install or synchronize declared development dependencies if needed**

Run only when the current environment is missing a declared tool:

```powershell
python -m pip install -r requirements-dev.txt
```

Network installation requires the normal approval prompt. Do not upgrade unrelated packages.

- [ ] **Step 2: Run the full test and coverage gate**

Run:

```powershell
pytest tests -q --cov=app --cov-fail-under=60
```

Expected: the `84` existing tests plus all new migration/deployment tests pass; the three platform/PostgreSQL skips remain explainable locally; coverage stays at or above `60%`. Record the exact final count from Pytest rather than inferring it.

- [ ] **Step 3: Run static and artifact checks**

Run:

```powershell
ruff check app tests scripts/run_migrations.py
mypy app
python -m compileall -q app scripts/run_migrations.py
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci-cd.yml', encoding='utf-8')); yaml.safe_load(open('docker-compose.portainer-neon.yml', encoding='utf-8')); print('yaml ok')"
git diff --check
git status --short --branch
```

If Bash is available, run `bash -n entrypoint.sh`. Expected: every executable check exits `0`, the branch contains only intentional committed changes, and no secret value appears in the diff.

- [ ] **Step 4: Review the branch diff against the specification**

Run:

```powershell
git diff master...HEAD --stat
git diff master...HEAD -- entrypoint.sh scripts/run_migrations.py .github/workflows/ci-cd.yml docker-compose.portainer-neon.yml tests/test_run_migrations.py tests/test_deployment_config.py
```

Verify line by line that every goal in the specification has a corresponding implementation and that no production action or credential is included.

---

### Task 5: Push the correction and verify Pull Request checks

**Files:**
- No new file changes expected.

**Interfaces:**
- Consumes branch: `codex/platform-hardening`.
- Produces updated Pull Request #1 and GitHub Actions evidence.

- [ ] **Step 1: Push the verified commits**

Run:

```powershell
git push origin codex/platform-hardening
```

Expected: the remote branch advances to the local head without force-push.

- [ ] **Step 2: Confirm GitHub creates PR checks**

Open `https://github.com/cezaralfredo/plataforma_atende_agenda/pull/1/checks` and verify that `Test & Lint` and `Validate container images` appear for the new head commit.

If the PR still reports zero checks, stop. Record the head SHA and treat repository Actions/event configuration as an external blocker; do not merge.

- [ ] **Step 3: Wait for all checks to finish**

Confirm:

- PostgreSQL service becomes healthy;
- Alembic upgrades the empty test database to head;
- Ruff, MyPy, tests, and coverage pass;
- runtime Dockerfile builds on Linux/AMD64;
- backup Dockerfile builds on Linux/AMD64.

On failure, inspect the exact failing job, reproduce locally where possible, create a failing regression test, and return to the relevant task. Do not merge or alter production.

- [ ] **Step 4: Report the verified handoff**

Report the Pull Request URL, new head commit, local verification counts, GitHub check statuses, and the remaining separately approved production sequence. Explicitly state that the PR remains unmerged and Portainer remains unchanged.
