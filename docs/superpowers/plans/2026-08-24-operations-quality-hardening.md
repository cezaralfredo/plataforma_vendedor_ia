# Operations and Quality Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make health reporting, backups, CI, deployment examples, logging, and documentation accurately reflect production behavior.

**Architecture:** Separate liveness from database readiness; ship a dedicated backup image with an independently testable script; make CI run the same PostgreSQL semantics used in production and publish one runtime plus one backup image only after verification.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL 16, Docker/Compose, GitHub Actions, Bash, pytest, Ruff, MyPy.

**Spec:** `docs/superpowers/specs/2026-08-24-platform-hardening-design.md`

## Global Constraints

- `/health` reports only process liveness; `/ready` verifies the database.
- Backup artifacts appear under their final name only after a successful, validated dump.
- VPS environment variables and Docker secrets use one script contract.
- One master push publishes each image once.
- CI type checking is enforcing, not advisory.
- Docker-dependent checks may be skipped locally only when Docker is unavailable; CI must execute them.

---

### Task 1: Readiness and protected observability

**Files:**
- Modify: `app/api/health.py`
- Modify: `app/main.py`
- Modify: `Dockerfile`
- Create: `tests/test_health.py`

**Interfaces:**
- Produces: `GET /ready` returning `{"status": "ready"}` or HTTP `503`.
- Consumes: protected metrics endpoint established by the security plan.

- [ ] **Step 1: Write failing readiness tests**

```python
def test_readiness_checks_database(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

def test_readiness_returns_503_on_database_failure(anonymous_client, monkeypatch):
    monkeypatch.setattr(Session, "execute", Mock(side_effect=SQLAlchemyError("offline")))
    response = anonymous_client.get("/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "Database unavailable"
```

- [ ] **Step 2: Run and observe `/ready` returns 404**

Run: `pytest tests/test_health.py -v`

- [ ] **Step 3: Implement readiness with `SELECT 1`**

```python
@router.get("/ready")
def readiness_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ready"}
```

Change Docker `HEALTHCHECK` from `/health` to `/ready`.

- [ ] **Step 4: Run health and auth tests**

Run: `pytest tests/test_health.py tests/test_authentication.py -v`

- [ ] **Step 5: Commit**

```text
git add app/api/health.py app/main.py Dockerfile tests/test_health.py
git commit -m "fix: distinguish liveness from readiness"
```

### Task 2: Error logging without leaking internals

**Files:**
- Modify: `app/mcp/tools.py`
- Modify: `app/services/payment_service.py`
- Create: `tests/test_error_logging.py`

**Interfaces:**
- Produces module loggers using Python `logging`.
- Changes MCP unexpected error text to `Erro interno ao processar a solicitação.`.

- [ ] **Step 1: Write failing redaction and logging tests**

```python
def test_mcp_does_not_return_internal_exception(client, monkeypatch, caplog):
    monkeypatch.setattr(UserService, "get", Mock(side_effect=RuntimeError("database password leaked")))
    response = mcp_call(client, "atualizar_cliente", {"user_id": 1, "name": "Ana"})
    text = response.json()["result"]["content"][0]["text"]
    assert "database password leaked" not in text
    assert "database password leaked" in caplog.text

def test_recent_payment_failure_is_logged(db_session, caplog):
    service = service_with_failing_pending_payment(db_session)
    asyncio.run(service.verify_recent_payments())
    assert "payment_id=" in caplog.text
```

- [ ] **Step 2: Verify MCP leaks the exception and payment verification is silent**

Run: `pytest tests/test_error_logging.py -v`

- [ ] **Step 3: Log identifiers and return generic caller errors**

```python
logger = logging.getLogger(__name__)

except Exception:
    logger.exception("MCP tool failed", extra={"tool_name": name})
    return {"isError": True, "content": [{"type": "text", "text": "Erro interno ao processar a solicitação."}]}
```

In recent payment verification, log payment ID and appointment ID with `logger.exception`, then continue.

- [ ] **Step 4: Run MCP/payment tests**

Run: `pytest tests/test_error_logging.py tests/test_mcp_clientes.py tests/test_flow_completo.py -v`

- [ ] **Step 5: Commit**

```text
git add app/mcp/tools.py app/services/payment_service.py tests/test_error_logging.py
git commit -m "fix: log integration failures safely"
```

### Task 3: Reliable backup script and image

**Files:**
- Modify: `scripts/backup.sh`
- Create: `Dockerfile.backup`
- Modify: `docker-compose.prod.yml`
- Modify: `docker-compose.vps.yml`
- Create: `tests/test_backup_script.py`

**Interfaces:**
- Consumes env: `POSTGRES_PASSWORD_FILE` or `POSTGRES_PASSWORD`, `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, `RCLONE_DESTINATION`.
- Produces image: `${REGISTRY}/${GITHUB_REPOSITORY}-backup:latest`.

- [ ] **Step 1: Write failing Bash integration tests**

```python
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")
def test_failed_dump_does_not_publish_backup(tmp_path):
    bin_dir = install_stub(tmp_path, "pg_dump", "#!/bin/sh\nexit 2\n")
    result = run_backup(tmp_path, bin_dir, POSTGRES_PASSWORD="secret")
    assert result.returncode != 0
    assert list(tmp_path.glob("*.sql.gz")) == []

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")
def test_env_password_creates_valid_nonempty_gzip(tmp_path):
    bin_dir = install_stub(tmp_path, "pg_dump", "#!/bin/sh\nprintf '%s\\n' 'CREATE TABLE ok();'\n")
    result = run_backup(tmp_path, bin_dir, POSTGRES_PASSWORD="secret")
    assert result.returncode == 0
    backups = list(tmp_path.glob("agenda_agenda_atende_*.sql.gz"))
    assert len(backups) == 1
    assert gzip.decompress(backups[0].read_bytes()).startswith(b"CREATE TABLE")
```

- [ ] **Step 2: Run and observe pipeline success on failed dump and env-password failure**

Run: `pytest tests/test_backup_script.py -v`

- [ ] **Step 3: Implement atomic validated backups**

Start with `set -euo pipefail`. Resolve the password:

```bash
if [ -n "${POSTGRES_PASSWORD_FILE:-}" ]; then
    PGPASSWORD="$(tr -d '\r\n' < "$POSTGRES_PASSWORD_FILE")"
else
    PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD or POSTGRES_PASSWORD_FILE is required}"
fi
export PGPASSWORD
```

Write `pg_dump | gzip` to `*.tmp`, run `test -s` and `gzip -t`, then `mv` to the final filename. Trap removes the temporary file. Validate retention with a numeric shell case. Use configurable `BACKUP_DIR` for tests.

Create:

```dockerfile
FROM postgres:16-alpine
RUN apk add --no-cache rclone
COPY scripts/backup.sh /backup.sh
RUN chmod 0755 /backup.sh
ENTRYPOINT ["/backup.sh"]
```

Compose uses the backup image, passes `POSTGRES_PASSWORD_FILE` for secrets in prod, and passes `POSTGRES_PASSWORD` in VPS.

- [ ] **Step 4: Run script tests and build when Docker is available**

Run: `pytest tests/test_backup_script.py -v`

Run: `docker build -f Dockerfile.backup -t agenda-atende-backup:test .`

Expected: tests pass; Docker build exits zero. If Docker is unavailable locally, record that fact and require the CI build in Task 5.

- [ ] **Step 5: Commit**

```text
git add scripts/backup.sh Dockerfile.backup docker-compose.prod.yml docker-compose.vps.yml tests/test_backup_script.py
git commit -m "fix: make scheduled backups reliable"
```

### Task 4: PostgreSQL-capable test fixtures and migration smoke test

**Files:**
- Modify: `tests/conftest.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci-cd.yml`
- Create: `tests/test_migrations.py`

**Interfaces:**
- Consumes: `TEST_DATABASE_URL`.
- Produces pytest marker: `postgres`.

- [ ] **Step 1: Add a failing CI assertion that the integration database is PostgreSQL**

```python
@pytest.mark.postgres
def test_postgres_integration_job_uses_postgres(db_session):
    assert db_session.bind.dialect.name == "postgresql"
```

Add migration test invoking Alembic against an empty PostgreSQL database and asserting `alembic current` contains the repository head revision.

- [ ] **Step 2: Run locally in SQLite and verify the PostgreSQL marker skips cleanly**

Run: `pytest tests/test_migrations.py -v`

- [ ] **Step 3: Make fixture engine configuration conditional**

```python
engine_kwargs = {}
if TEST_DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
engine = create_engine(TEST_DATABASE_URL, **engine_kwargs)
```

Register the marker in `pyproject.toml`. In CI, set `TEST_DATABASE_URL=postgresql+psycopg://test:test@localhost:5432/test_db` for the full test step. Use a separate empty database/schema for migration smoke so fixture drops cannot invalidate migration verification.

- [ ] **Step 4: Run SQLite locally and PostgreSQL in CI-equivalent environment**

Run: `pytest tests -v`

Run with PostgreSQL: `pytest tests -v --cov=app --cov-report=xml --cov-fail-under=60`

Run: `alembic upgrade head && alembic check`

- [ ] **Step 5: Commit**

```text
git add tests/conftest.py tests/test_migrations.py pyproject.toml .github/workflows/ci-cd.yml
git commit -m "test: exercise production PostgreSQL behavior"
```

### Task 5: Single enforcing CI and two image outputs

**Files:**
- Modify: `.github/workflows/ci-cd.yml`
- Delete: `.github/workflows/publish-image.yml`
- Modify: `app/repositories/base.py`
- Modify: `app/services/availability_service.py`
- Modify: `app/mcp/tools.py`

**Interfaces:**
- Produces runtime tags under `${REGISTRY}/${IMAGE_NAME}`.
- Produces backup tags under `${REGISTRY}/${IMAGE_NAME}-backup`.

- [ ] **Step 1: Add a workflow-structure regression test**

Create assertions in `tests/test_deployment_config.py`:

```python
def test_only_one_workflow_publishes_latest():
    workflows = Path(".github/workflows").glob("*.yml")
    publishers = [path for path in workflows if "build-push-action" in path.read_text()]
    assert [path.name for path in publishers] == ["ci-cd.yml"]

def test_ci_type_check_is_not_advisory():
    workflow = Path(".github/workflows/ci-cd.yml").read_text()
    assert "mypy app/ --ignore-missing-imports || true" not in workflow
    assert "mypy app/ --ignore-missing-imports" in workflow
```

Run the current type check as the second red assertion:

```text
mypy app --ignore-missing-imports
```

- [ ] **Step 2: Run and observe two publisher workflows, advisory CI, and 28 current type errors**

Run: `pytest tests/test_deployment_config.py -v`

- [ ] **Step 3: Consolidate workflow and make checks enforcing**

Delete `publish-image.yml`. Keep the runtime build and add a second `docker/build-push-action` step using `Dockerfile.backup` and tags `${REGISTRY}/${IMAGE_NAME}-backup:latest` plus SHA. Pin MyPy to `1.17.1` in CI and run `mypy app --ignore-missing-imports` without `|| true`.

Make the current typing corrections explicitly:

- In `BaseRepository.get`, use `filter_by(id=id)` so the generic declarative base is not required to declare `id`.
- In `AvailabilityService`, import `List` from `typing` and use `List[TimeSlot]` for annotations inside the class, avoiding collision with its `list` method.
- In `handle_tool_call`, replace reused `svc`, `data`, and result variables with branch-specific names such as `user_service`, `appointment_service`, `user_update`, and `appointment`; pass `datetime.now()` directly to `AppointmentUpdate.notified_at`.

- [ ] **Step 4: Validate workflow and type checking**

Run: `pytest tests/test_deployment_config.py -v`

Run: `mypy app --ignore-missing-imports`

Expected: both exit zero. GitHub Actions then validates both multi-architecture image builds.

- [ ] **Step 5: Commit**

```text
git add .github/workflows tests/test_deployment_config.py app/repositories/base.py app/services/availability_service.py app/mcp/tools.py
git commit -m "ci: publish verified runtime and backup images once"
```

### Task 6: Correct deployment examples and remove broken seed path

**Files:**
- Modify: `.env.prod.example`
- Modify: `docker-compose.prod.yml`
- Modify: `docker-compose.vps.yml`
- Modify: `entrypoint.sh`
- Modify: `tests/test_deployment_config.py`

**Interfaces:**
- Changes example `DOMAIN=seudominio.com`.
- Requires full `GITHUB_REPOSITORY=cezaralfredo/plataforma_atende_agenda` example.

- [ ] **Step 1: Add failing configuration assertions**

```python
def test_domain_example_produces_single_api_prefix():
    env = parse_env_example()
    assert env["DOMAIN"] == "seudominio.com"

def test_registry_repository_example_is_complete():
    env = parse_env_example()
    assert env["GITHUB_REPOSITORY"] == "cezaralfredo/plataforma_atende_agenda"

def test_runtime_entrypoint_does_not_call_removed_test_seed():
    assert "python -m tests.seed" not in Path("entrypoint.sh").read_text()
```

- [ ] **Step 2: Run and observe double `api` domain, missing image owner, and broken seed command**

Run: `pytest tests/test_deployment_config.py -v`

- [ ] **Step 3: Correct examples and entrypoint**

Set the root domain and uncomment the full repository example. Remove `SEED_DATA` from compose environments and remove the entrypoint branch that imports `tests.seed`. Put cron explanations on their own comment lines so `BACKUP_SCHEDULE` contains only `0 3 * * *`.

- [ ] **Step 4: Validate tests and both Compose variants**

Run: `pytest tests/test_deployment_config.py -v`

Run: `docker compose -f docker-compose.prod.yml --env-file .env.prod.example config --quiet`

Run: `docker compose -f docker-compose.vps.yml --env-file .env.prod.example config --quiet`

- [ ] **Step 5: Commit**

```text
git add .env.prod.example docker-compose.prod.yml docker-compose.vps.yml entrypoint.sh tests/test_deployment_config.py
git commit -m "fix: align production deployment examples"
```

### Task 7: Documentation and final verification

**Files:**
- Modify: `README.md`
- Modify: `DEPLOY_VPS.md`
- Modify: `DEPLOY_PORTAINER.md`
- Modify: `DEPLOY_NGINX_PORTAINER.md`
- Modify: `DEPLOY_PORTAINER_NPM.md`

**Interfaces:**
- Documents the implemented security, Asaas, timezone, readiness, backup, and MCP contracts.

- [ ] **Step 1: Add documentation consistency tests**

Extend `tests/test_deployment_config.py`:

```python
def test_readme_documents_authenticated_api_and_current_asaas_urls():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "Authorization: Bearer" in readme
    assert "https://api-sandbox.asaas.com/v3" in readme
    assert "/ready" in readme
    assert "buscar_cliente_por_telefone" in readme
```

- [ ] **Step 2: Run and observe outdated documentation**

Run: `pytest tests/test_deployment_config.py -v`

- [ ] **Step 3: Update all operational documentation**

Document Bearer headers on `/api`, Basic browser access for `/admin`, disabled production docs, protected metrics, current Asaas URLs and external references, `APP_TIMEZONE`, expiry behavior, `/ready`, runtime/backup images, PostgreSQL CI, migration preflight, and all 12 MCP tools. Remove instructions that imply local-only refund or unauthenticated API usage.

- [ ] **Step 4: Run complete verification from a clean process**

Run: `pytest tests -v --cov=app --cov-report=term-missing --cov-fail-under=60`

Run: `ruff check app tests`

Run: `python -m compileall -q app tests`

Run: `mypy app --ignore-missing-imports`

Run with PostgreSQL: `alembic upgrade head && alembic check`

Run when Docker is available: `docker build -f Dockerfile -t agenda-atende:test .`

Run when Docker is available: `docker build -f Dockerfile.backup -t agenda-atende-backup:test .`

Run when Docker is available: both production Compose `config --quiet` commands from Task 6.

- [ ] **Step 5: Inspect final diff and commit documentation**

Run: `git diff --check`

Run: `git status --short`

```text
git add README.md DEPLOY_VPS.md DEPLOY_PORTAINER.md DEPLOY_NGINX_PORTAINER.md DEPLOY_PORTAINER_NPM.md tests/test_deployment_config.py
git commit -m "docs: describe hardened production operation"
```
