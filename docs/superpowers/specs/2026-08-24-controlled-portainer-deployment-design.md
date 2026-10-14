# Controlled Portainer Deployment Design

## Context

The production stack named `atende_agenda` runs on Portainer Community Edition with Docker Standalone and Nginx Proxy Manager. The API currently connects to an external Neon PostgreSQL database, while an older local PostgreSQL container and volume remain attached to the Compose project.

The current deployment path has four coupled problems:

1. `entrypoint.sh` waits for a host named `postgres` even when `DATABASE_URL` targets Neon. The local PostgreSQL container is therefore an artificial startup dependency.
2. The CI workflow configures `DATABASE_URL` with the legacy `postgresql://` scheme even though the repository standardizes on Psycopg 3 and `postgresql+psycopg://`.
3. Pull Request #1 has no GitHub checks. The next branch update must trigger and expose the PR test run before merge.
4. The deploy job can finish with every deployment step skipped, and the Portainer stack uses the mutable `latest` tag. A green workflow therefore does not prove that a specific artifact reached production.

The current Portainer editor also contains the external database connection string directly in the Compose source. This design removes that value from the stack document, but it does not claim that Portainer environment variables are equivalent to Swarm secrets: Portainer administrators and Docker inspection can still access container environment values.

## Goals

- Make API startup depend only on the configured `DATABASE_URL`.
- Run Alembic migrations against that configured database with bounded retries before starting Uvicorn.
- Make Pull Request checks exercise linting, typing, PostgreSQL migrations, tests, and Docker image construction.
- Publish traceable runtime and backup images from `master` using commit-derived tags.
- Prevent CI from reporting an automatic production deployment that did not occur.
- Provide a Portainer + Neon Compose definition with no local PostgreSQL service and no literal database credential in the YAML.
- Preserve a controlled rollback path and keep production unchanged until a separate approved deployment step.

## Non-goals

- This change does not merge Pull Request #1.
- This change does not edit or restart the live Portainer stack.
- This change does not rotate the Neon credential.
- This change does not remove the local PostgreSQL container or volume.
- This change does not automate Portainer through an administrative API token.
- This change does not replace Neon backup or point-in-time recovery procedures.

## Considered approaches

### Selected: configured-database migration runner and controlled deployment

A small Python migration runner invokes `alembic upgrade head`, retries transient failures, exits non-zero after a bounded number of attempts, and never parses or logs the database URL. The runtime entrypoint loads file-backed secrets when configured, invokes the runner, and starts Uvicorn only after migrations succeed.

CI tests and builds the images, but production deployment remains an explicit Portainer operation using a commit-derived image tag. This separates artifact creation from credential rotation and live database changes.

### Rejected: parse `DATABASE_URL` and call `pg_isready`

This duplicates connection handling, requires translating SQLAlchemy schemes such as `postgresql+psycopg://` into libpq-compatible URLs, and can disagree with the connection Alembic will actually use. Retrying Alembic tests the real boundary instead.

### Rejected: retain the local PostgreSQL sidecar as a readiness dependency

The sidecar is not the configured data store and creates a hidden production dependency. It also prevents safe cleanup of an otherwise unused container and volume.

### Deferred: fully automated Portainer deployment

Updating an immutable image tag through the Portainer API requires persistent administrative credentials and a tested rollback controller. That is unnecessary for the current repair and should be designed separately if automatic production deployment becomes a requirement.

## Runtime design

### Migration runner

Create `scripts/run_migrations.py` with one public operation that:

- executes `alembic upgrade head` through `subprocess.run`;
- retries a failed command using bounded attempt and delay settings;
- defaults to 30 attempts with a two-second delay;
- prints only attempt counts and command outcome, never connection strings or environment values;
- returns normally on success and re-raises the final process failure on exhaustion.

The retry function accepts the process runner and sleeper as injectable callables so tests exercise retry behavior without a real database or arbitrary waits. The executable module reads optional positive values from `MIGRATION_MAX_ATTEMPTS` and `MIGRATION_RETRY_DELAY_SECONDS`.

### Entrypoint

`entrypoint.sh` will:

1. load `DATABASE_URL`, `POSTGRES_PASSWORD`, API keys, and Asaas keys from their corresponding `_FILE` variables when present;
2. retain password placeholder substitution for the repository's local PostgreSQL Compose definitions;
3. remove the hard-coded `pg_isready -h postgres` loop;
4. run `python /app/scripts/run_migrations.py`;
5. start Uvicorn only after migrations succeed.

This supports both the local PostgreSQL service and external Neon without branching on provider or hostname.

## CI and artifact design

Create `requirements-dev.txt` so local and CI validation use the same declared tools: runtime requirements, Pytest coverage, Ruff, MyPy, and PyYAML.

The GitHub workflow will:

- use `postgresql+psycopg://` consistently for Alembic and PostgreSQL tests;
- run Ruff, MyPy, migrations, and the full test suite on Pull Requests;
- parse deployment YAML in tests instead of relying only on source substring checks;
- build the runtime and backup Dockerfiles on Pull Requests without pushing;
- build and publish multi-architecture runtime and backup images only after a successful `master` test run;
- publish `latest` for compatibility and a commit-derived tag for controlled deployment;
- remove the automatic deploy job so a skipped webhook or SSH step cannot be reported as a deployment.

The corrective branch update is also the trigger used to verify whether GitHub Actions attaches checks to Pull Request #1. If the PR still shows zero checks, repository Actions settings become a separate external blocker and merging remains disallowed.

## Portainer + Neon stack design

Add a dedicated Compose definition for the actual production topology:

- one API service, with no PostgreSQL service;
- image tag supplied through required `IMAGE_TAG` rather than `latest`;
- `DATABASE_URL`, API keys, and Asaas credentials supplied through Portainer's environment-variable table rather than written into the Compose editor;
- explicit `APP_TIMEZONE`, defaulting to `America/Sao_Paulo`;
- `DEBUG=false`;
- the external Nginx Proxy Manager network and existing `agenda-api` alias;
- no published host port;
- `restart: unless-stopped` and the image-provided `/ready` health check.

The existing local-PostgreSQL Portainer Compose remains available for installations that intentionally host their database in the same project. Documentation will distinguish the two topologies and warn that Docker Standalone environment variables are not opaque secrets.

## Testing strategy

### Automated behavior tests

- Migration succeeds on the first attempt without sleeping.
- Migration retries a transient failure and then succeeds.
- Migration raises the final failure after the configured attempt limit.
- Invalid retry settings fail closed with a clear configuration error.

These tests exercise the real retry function and replace only the external process and time boundaries.

### Configuration validation

- Parse the GitHub workflow and Compose files with PyYAML.
- Assert that CI uses the Psycopg 3 URL scheme for migrations and tests.
- Assert that Pull Requests include both the test job and non-publishing image builds.
- Assert that no automatic deploy job remains.
- Assert that the Neon Compose has no PostgreSQL service, requires an immutable image tag, configures `APP_TIMEZONE`, and does not contain a literal database URL.

### Final verification

- Run targeted migration and deployment tests through their red-green cycles.
- Run the complete Pytest suite with the coverage threshold.
- Run Ruff, MyPy, compileall, YAML parsing, shell syntax validation when Bash is available, and `git diff --check`.
- Push the new commits and verify that Pull Request #1 shows the GitHub checks and their final status.

Docker is not available in the local Windows workspace, so Linux image construction is an explicit GitHub Actions gate rather than a local claim.

## Controlled rollout after merge

The later production rollout must remain a separately approved operation:

1. Verify a current Neon restore point or create a logical backup.
2. Create a replacement database credential without revoking the active credential.
3. Wait for the `master` workflow to publish the commit-derived image tag.
4. Update the Portainer stack environment and Compose definition without deleting the old PostgreSQL container or volume.
5. Deploy the immutable image tag and verify `/ready`, migrations, logs, scheduling, MCP, payments, and webhooks.
6. Revoke the previous database credential only after the new deployment is healthy.
7. Keep the previous image digest and stack definition available for rollback.
8. After an observation period, confirm that the local PostgreSQL service has no dependency or required data, create a backup, and request separate approval before removing its container or volume.

## Rollback

If startup, migrations, or application validation fails, restore the prior Portainer stack definition and prior image digest. Do not revoke the previous Neon credential until the new deployment has passed validation. Database downgrade migrations are not automatic; any schema rollback requires a separate reviewed plan based on the exact migration applied.

## Security constraints

- No credential value is added to Git, logs, tests, documentation examples, or GitHub Actions output.
- Retry logs never print `DATABASE_URL`.
- Production changes, credential rotation, stack recreation, and volume removal require separate action-time approval.
- The local PostgreSQL volume is treated as potentially material data until backed up and explicitly cleared for deletion.
