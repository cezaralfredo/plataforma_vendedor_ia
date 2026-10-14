# Platform Hardening Design

**Date:** 2026-08-24

## Purpose

Harden Agenda Atende for production use without replacing its current FastAPI, SQLAlchemy, PostgreSQL, Asaas, MCP, and Jinja architecture. The work is split into three independently verifiable packages: security and financial integration, scheduling and data integrity, and operations and quality.

## Success criteria

- Personal and operational data under `/api` cannot be read or changed without the configured API key.
- The HTML admin panel works through normal browser navigation without exposing the admin key in page source.
- Asaas calls use the current endpoints, reconcile uncertain creates, and never report a local refund that was not accepted by Asaas.
- Webhook delivery is authenticated, idempotent by provider event, and transactionally updates payment and appointment state.
- Expired reservations stop blocking the schedule, and a late payment never reactivates a cancelled appointment automatically.
- Offset-aware and offset-naive appointment input is handled consistently in `America/Sao_Paulo`.
- PostgreSQL prevents simultaneous overlapping appointments for a professional.
- Production migrations and ORM metadata enforce the same invariants.
- Backup failures fail visibly; successful archives are non-empty, valid gzip files, and optionally uploaded with an installed `rclone` binary.
- CI exercises PostgreSQL behavior in addition to the fast SQLite suite.
- All corrected behavior has a regression test that was observed failing before implementation.

## Constraints and non-goals

- Preserve existing resource paths and response shapes unless a security or integrity correction requires otherwise.
- Reuse `API_KEY` and `ADMIN_API_KEY`; do not introduce user accounts or a new identity provider.
- Keep `/health` and `/webhooks/asaas` publicly reachable. MCP keeps its Bearer authentication.
- Disable interactive API documentation in production and protect `/metrics`; neither endpoint is a public product interface.
- Do not redesign the admin UI, replace SQLAlchemy's current query style, or perform a broad dependency upgrade.
- Do not silently repair conflicting production appointments during migration. Abort with an actionable database error so an operator can reconcile the records.
- Do not add a background queue in this hardening cycle. Webhooks remain synchronous and lightweight.

## Package 1: Security and financial integration

### API authentication

Create one shared authentication module. `/api` routers require `Authorization: Bearer <API_KEY>` through router-level dependencies. Token comparison uses `hmac.compare_digest`. Missing or invalid credentials return `401` with a Bearer challenge.

`/mcp` reuses the same verifier without changing its JSON-RPC behavior. `/metrics` requires the API key. FastAPI's `/docs`, `/redoc`, and `/openapi.json` are available only when `DEBUG=true`. `/health`, `/ready`, and the Asaas webhook remain outside API-key authentication.

Production startup rejects empty or known development values for `API_KEY`, `ADMIN_API_KEY`, and `ASAAS_WEBHOOK_TOKEN`. Development keeps explicit defaults only while `DEBUG=true`.

### Admin authentication

The admin panel accepts HTTP Basic authentication, using any non-empty username and `ADMIN_API_KEY` as the password. It continues accepting `X-Admin-Key` for existing machine clients. Invalid browser requests return `401` and `WWW-Authenticate: Basic realm="Agenda Atende Admin"`; invalid explicit `X-Admin-Key` requests return `403`.

Admin templates stop embedding `X-Admin-Key`. Same-origin links and `fetch` requests rely on the browser's Basic credentials. This removes the secret from HTML and makes navigation work normally.

### Asaas client contract

Defaults and examples use:

- Sandbox: `https://api-sandbox.asaas.com/v3`
- Production: `https://api.asaas.com/v3`

Every request sends `access_token`, JSON content headers, and a stable `User-Agent` derived from `APP_NAME`.

Automatic retry is limited to safe GET operations and transient `429`/`5xx`, timeout, or connection failures. Mutating POST operations are not blindly retried.

Customer creation uses `externalReference=user:{user_id}`. Before creating a customer, the service searches Asaas by that reference. It reuses exactly one match, creates when there is none, and raises a reconciliation error when multiple matches exist.

Charge creation uses `externalReference=appointment:{appointment_id}`. Before POSTing, the service checks both the local active payment and Asaas by external reference. After an inconclusive timeout, it performs one reconciliation lookup. Exactly one remote match is persisted locally; multiple matches cause an explicit reconciliation error instead of choosing silently.

Integration failures are logged with identifiers but never API keys or complete customer payloads. API callers receive `502` for rejected/unavailable upstream operations and `504` for an unresolved timeout.

### Payment and refund state

The Asaas client implements the documented full-refund endpoint `POST /payments/{asaas_payment_id}/refund`. The admin refund action becomes asynchronous and calls Asaas first. Local status changes to `refunded` only after a successful upstream response. A completed appointment remains completed; any other linked appointment becomes cancelled after a successful refund.

The manual refresh action calls the existing payment status service instead of returning an instruction string. Frequent Hermes polling is removed; webhooks are the primary synchronization mechanism and manual refresh remains available for reconciliation.

### Webhook processing

Webhook authentication always requires the configured `asaas-access-token`. Production cannot start without a non-development token.

Idempotency uses the provider's top-level event `id`. For legacy payloads without an ID, a SHA-256 digest of the canonical JSON body is used. The idempotency row and state updates commit in one transaction, including supported events that do not change the current state and unknown events. Duplicate inserts return `ignored/duplicate` without changing state.

State transitions are:

- `PAYMENT_RECEIVED` and `PAYMENT_CONFIRMED`: update the payment; confirm only appointments currently `pending` or `awaiting_payment` and not expired.
- `PAYMENT_OVERDUE` and `PAYMENT_CANCELLED`: update the payment; cancel appointments still `pending` or `awaiting_payment`.
- `PAYMENT_REFUNDED`: update the payment; cancel the appointment unless it is already `completed`.
- A received payment for an expired or cancelled appointment is recorded but never reactivates the appointment. The mismatch remains visible for admin reconciliation/refund.
- Unknown events are durably recorded and acknowledged without changing business state.

## Package 2: Scheduling and data integrity

### Time-zone policy

Add `APP_TIMEZONE`, defaulting to `America/Sao_Paulo`, and use `zoneinfo.ZoneInfo`.

Naive appointment input is interpreted as local business time for backward compatibility. Aware input is converted to business time. Availability windows are constructed with the business timezone, so all comparisons are aware. PostgreSQL continues storing `TIMESTAMP WITH TIME ZONE`; API responses retain an explicit UTC offset.

Appointments must start and end on the same local business date. Duration validation occurs after normalization.

### Reservation lifecycle

Both `pending` and `awaiting_payment` reservations expire at `expires_at`. Creating a charge preserves the original 30-minute expiry and rejects an already expired appointment. Expiration is applied before appointment creation/list/get/confirm and before availability calculations.

Conflict queries consider `confirmed` and `completed` appointments active. They consider `pending` and `awaiting_payment` active only while unexpired. Cancelled records never block availability.

Cancellation is idempotent for an already cancelled appointment and rejected for completed appointments. Confirmation is idempotent for an already confirmed appointment, allowed only from a non-expired `pending` or `awaiting_payment` state, and rejected for cancelled or completed records.

### Concurrent booking protection

Keep the service-level conflict check for friendly errors and SQLite tests. Add PostgreSQL's `btree_gist` extension and an exclusion constraint over professional ID and `[start_time, end_time)` for statuses `pending`, `awaiting_payment`, `confirmed`, and `completed`.

Before creating the constraint, the migration checks for existing overlapping active appointments and aborts with an error that lists the need for manual reconciliation. A database conflict during creation is translated to HTTP `409`, and the session is rolled back before reuse.

### Schema invariants and CRUD behavior

Models and migrations enforce:

- appointment end after start and allowed status;
- availability type exclusivity, day range, non-null times, and end after start;
- service duration greater than zero and price non-negative;
- payment amount non-negative, allowed billing type, and allowed status.

Partial updates pass `exclude_unset=True`. The repository writes explicitly provided `None`, allowing nullable fields such as notes, email, bio, photo, and category to be cleared. Availability updates validate the fully merged record before persistence.

Service and availability creation validate that the professional exists. User updates go through `UserService`, preserving phone uniqueness and translating duplicate phone/email errors to `409`. Foreign-key delete conflicts return `409` with guidance instead of leaking an internal database error. Professionals with history should be deactivated rather than deleted.

### Admin query correctness

Appointment lists and detail select one deterministic latest payment per appointment, preventing duplicates when payment history exists. Pagination requires positive page values and a bounded page size. `payments_pending` counts only `pending`; confirmed/received payments remain revenue, not pending work.

## Package 3: Operations and quality

### Health and observability

`/health` remains a process liveness check. Add `/ready`, which runs `SELECT 1` and returns `503` when the database is unavailable. Container health checks use `/ready`.

Expected integration failures and swallowed payment-verification failures are logged with structured identifiers. MCP returns a generic internal error to callers and logs the detailed exception server-side.

### Backup image and script

Create a dedicated backup image based on `postgres:16-alpine` with `rclone` installed. CI publishes it as `<registry>/<repository>-backup:latest`, and production/VPS compose files use that image.

The script uses `set -euo pipefail`, reads the password from `POSTGRES_PASSWORD_FILE` when present and otherwise from `POSTGRES_PASSWORD`, exports `PGPASSWORD`, writes to a temporary filename, verifies a non-empty gzip stream, and atomically renames it to the final backup filename. Failed dumps never appear as successful archives.

Remote upload runs only when both destination and configuration are present. Local retention uses a validated positive integer. The VPS and Docker-secret variants use the same script contract.

The unused production `SEED_DATA` branch is removed because tests are not shipped in the runtime image.

### CI and deployment

The test fixture supports SQLite and PostgreSQL engine configuration. CI runs the full suite against PostgreSQL with `TEST_DATABASE_URL`, while a fast local SQLite run remains supported. Migration smoke testing upgrades an empty PostgreSQL database to head and checks model/migration drift.

Consolidate duplicate image-publishing workflows so one master push cannot race two builds for `latest`. The remaining workflow builds and publishes the runtime and backup images after tests pass. Type checking installs MyPy, runs `mypy app --ignore-missing-imports` without `|| true`, and blocks the build on an error.

Compose examples use a root domain such as `seudominio.com`, producing `api.seudominio.com`, and specify the full `GITHUB_REPOSITORY`. Inline cron comments are removed from environment values.

### Documentation and test coverage

Update README and production examples for Bearer authentication, Basic admin access, current Asaas URLs, timezone semantics, readiness, backup image, and all MCP tools.

Add focused regression suites for authentication, admin navigation, Asaas reconciliation/refund, webhook idempotency and transitions, timezone-aware booking, expiry, concurrency error translation, nullable updates, admin query uniqueness, and backup-script validation. Coverage must remain at least 60%, with the corrected modules materially covered beyond the current baseline.

## Delivery sequence

1. Establish regression tests and shared auth/integration error primitives.
2. Correct API/admin security and Asaas/webhook behavior.
3. Correct timezone, lifecycle, CRUD, and PostgreSQL invariants.
4. Correct admin queries, readiness, backup, CI, compose, and documentation.
5. Run targeted tests after every behavior change, then the full test suite, Ruff, compilation, migration smoke tests, and compose validation when Docker is available.

## Rollback and deployment notes

- Authentication is the only intentional API compatibility break. Clients must send the existing `API_KEY` as a Bearer token when the hardened version deploys.
- Apply the database migration before serving traffic with the new application image. The migration aborts rather than accepting existing conflicting active appointments.
- Keep the previous runtime image tag available. Application rollback is safe while the new additive constraints remain, provided old code writes values that satisfy them.
- Rotate any admin key that may previously have been exposed through rendered page source.
- Deploy Asaas URL changes with environment-matching keys and validate the complete flow in Sandbox before production.
- Verify one local backup, one restore into a temporary database, and one remote upload before relying on the scheduled job.
