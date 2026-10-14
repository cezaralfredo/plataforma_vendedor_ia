# Security and Financial Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Protect internal interfaces and make Asaas creation, webhook, refresh, and refund flows financially consistent.

**Architecture:** Centralize API/admin authentication in `app/security.py`; keep Asaas HTTP concerns in `AsaasClient`; keep reconciliation and payment state in `PaymentService`. Webhook processing uses the provider event ID and a single database transaction.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, httpx, tenacity, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-platform-hardening-design.md`

## Global Constraints

- Reuse `API_KEY` and `ADMIN_API_KEY`.
- Keep `/health`, `/ready`, and `/webhooks/asaas` publicly reachable.
- Disable docs only when `DEBUG=false`; protect `/metrics` in every environment.
- Never retry mutating Asaas calls blindly.
- Never change local payment state before Asaas accepts a refund.
- Write and observe each regression test fail before production code changes.

---

### Task 1: Shared API and admin authentication

**Files:**
- Create: `app/security.py`
- Modify: `app/config.py`
- Modify: `app/main.py`
- Modify: `app/api/users.py`
- Modify: `app/api/professionals.py`
- Modify: `app/api/services.py`
- Modify: `app/api/availability.py`
- Modify: `app/api/appointments.py`
- Modify: `app/api/payments.py`
- Modify: `app/mcp/router.py`
- Modify: `app/admin/router.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_authentication.py`

**Interfaces:**
- Produces: `require_api_key(request: Request) -> None`
- Produces: `require_admin(request: Request, x_admin_key: str | None) -> None`
- Produces: `validate_production_secrets(settings: Settings) -> Settings`
- Produces: `create_app(app_settings: Settings = settings) -> FastAPI`

- [ ] **Step 1: Write failing authentication tests**

```python
def test_api_rejects_missing_bearer(anonymous_client):
    response = anonymous_client.get("/api/users")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"

def test_api_accepts_configured_bearer(anonymous_client):
    response = anonymous_client.get(
        "/api/users",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    )
    assert response.status_code == 200

def test_admin_basic_auth_survives_normal_navigation(anonymous_client):
    credentials = b64encode(f"admin:{settings.admin_api_key}".encode()).decode()
    response = anonymous_client.get(
        "/admin",
        headers={"Authorization": f"Basic {credentials}"},
    )
    assert response.status_code == 200
    assert settings.admin_api_key not in response.text

def test_metrics_requires_bearer(anonymous_client):
    assert anonymous_client.get("/metrics").status_code == 401

def test_production_rejects_development_secrets():
    with pytest.raises(ValidationError):
        Settings(
            debug=False,
            api_key="dev-api-key-change-in-production",
            admin_api_key="dev-admin-key-change-in-production",
            asaas_webhook_token="",
        )

def test_production_disables_interactive_docs(monkeypatch):
    production_app = create_app(Settings(debug=False, api_key="a" * 32, admin_api_key="b" * 32, asaas_webhook_token="c" * 32))
    paths = {route.path for route in production_app.routes}
    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths
```

- [ ] **Step 2: Run the tests and verify the current public/header-only behavior fails them**

Run: `pytest tests/test_authentication.py -v`

Expected: missing Bearer returns `200`, Basic admin returns `422`/`403`, or metrics returns `200`.

- [ ] **Step 3: Implement shared authentication and production-secret validation**

```python
def require_api_key(request: Request) -> None:
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {settings.api_key}"
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})

def require_admin(
    request: Request,
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    if x_admin_key is not None:
        if hmac.compare_digest(x_admin_key, settings.admin_api_key):
            return
        raise HTTPException(403, "Admin access denied")
    username, password = decode_basic_credentials(request)
    if not username or not hmac.compare_digest(password, settings.admin_api_key):
        raise HTTPException(
            401,
            "Admin authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Agenda Atende Admin"'},
        )
```

Apply `dependencies=[Depends(require_api_key)]` to every `/api` router. Reuse `require_api_key` in MCP. Build the application through `create_app`, set docs URLs from the passed settings, and retain `app = create_app()` for ASGI deployment. Replace automatic Instrumentator exposure with a `/metrics` response using `prometheus_client.generate_latest()` and `Depends(require_api_key)`.

In `tests/conftest.py`, keep `anonymous_client` without headers and make the existing `client` fixture add the configured Bearer header so current tests express the new contract.

- [ ] **Step 4: Run focused and existing tests**

Run: `pytest tests/test_authentication.py tests/test_flow_completo.py tests/test_mcp_clientes.py -v`

Expected: all pass.

- [ ] **Step 5: Commit**

```text
git add app/security.py app/config.py app/main.py app/api app/mcp/router.py app/admin/router.py tests
git commit -m "fix: protect api and admin interfaces"
```

### Task 2: Remove admin-key exposure from templates

**Files:**
- Modify: `app/admin/templates/dashboard.html`
- Modify: `app/admin/templates/appointments.html`
- Modify: `app/admin/templates/payments.html`
- Modify: `app/admin/templates/professionals.html`
- Modify: `app/admin/templates/appointment_detail.html`
- Modify: `tests/test_authentication.py`

**Interfaces:**
- Consumes: browser Basic authentication from Task 1.
- Produces: same-origin `fetch` calls without secret-bearing template interpolation.

- [ ] **Step 1: Add a failing rendered-page regression test**

```python
def test_admin_pages_do_not_render_admin_key(anonymous_client):
    headers = basic_admin_headers()
    for path in ("/admin", "/admin/appointments", "/admin/payments", "/admin/professionals"):
        response = anonymous_client.get(path, headers=headers)
        assert response.status_code == 200
        assert settings.admin_api_key not in response.text
        assert "X-Admin-Key" not in response.text
```

- [ ] **Step 2: Verify the test fails because templates contain `X-Admin-Key`**

Run: `pytest tests/test_authentication.py::test_admin_pages_do_not_render_admin_key -v`

- [ ] **Step 3: Remove every injected admin header**

Use same-origin fetch without a manual authentication header:

```javascript
const response = await fetch('/admin/api/kpis');
```

Keep JSON `Content-Type` for POST bodies but omit `X-Admin-Key`.

- [ ] **Step 4: Run the focused test and scan templates**

Run: `pytest tests/test_authentication.py -v`

Run: `rg -n "X-Admin-Key|admin_api_key|x-admin-key" app/admin/templates`

Expected: tests pass and the scan returns no matches.

- [ ] **Step 5: Commit**

```text
git add app/admin/templates tests/test_authentication.py
git commit -m "fix: keep admin secret out of rendered pages"
```

### Task 3: Safe Asaas HTTP client

**Files:**
- Modify: `app/services/asaas_client.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `.env.prod.example`
- Create: `tests/test_asaas_client.py`

**Interfaces:**
- Produces: `AsaasClient.list_customers(external_reference: str) -> list[dict]`
- Produces: `AsaasClient.list_payments(..., external_reference: str | None) -> list[dict]`
- Produces: `AsaasClient.create_customer(..., external_reference: str) -> dict`
- Produces: `AsaasClient.create_payment(..., external_reference: str) -> dict`
- Produces: `AsaasClient.refund_payment(payment_id: str) -> dict`
- Produces: `AsaasIntegrationError` and `AsaasUncertainResultError`.

- [ ] **Step 1: Write failing transport-contract tests using `httpx.MockTransport`**

```python
def test_client_uses_current_sandbox_url_and_user_agent(monkeypatch):
    request = capture_request(monkeypatch, response_json={"data": []})
    asyncio.run(AsaasClient().list_payments(external_reference="appointment:7"))
    assert str(request.url) == "https://api-sandbox.asaas.com/v3/payments?limit=10&externalReference=appointment%3A7"
    assert request.headers["access_token"] == settings.asaas_api_key
    assert request.headers["user-agent"].startswith(settings.app_name)

def test_create_payment_sends_external_reference(monkeypatch):
    request = capture_post(monkeypatch, {"id": "pay_1"})
    asyncio.run(AsaasClient().create_payment(
        customer_id="cus_1", value=50, due_date="2026-08-25",
        billing_type="PIX", external_reference="appointment:12",
    ))
    assert json.loads(request.content)["externalReference"] == "appointment:12"

def test_mutating_timeout_is_not_retried(monkeypatch):
    calls = install_timeout_transport(monkeypatch)
    with pytest.raises(AsaasUncertainResultError):
        asyncio.run(AsaasClient().create_payment(
            customer_id="cus_1", value=50, due_date="2026-08-25",
            billing_type="PIX", external_reference="appointment:12",
        ))
    assert calls.count == 1
```

- [ ] **Step 2: Run and observe failures from old URL, missing fields, and three POST attempts**

Run: `pytest tests/test_asaas_client.py -v`

- [ ] **Step 3: Implement the safe client**

Set `asaas_base_url = "https://api-sandbox.asaas.com/v3"`. Add `User-Agent`. Keep tenacity only on GET methods and retry only timeouts, connection errors, `429`, and `5xx`. Convert non-success responses to `AsaasIntegrationError`; convert mutation timeout/connection loss to `AsaasUncertainResultError` without retrying.

```python
async def refund_payment(self, payment_id: str) -> dict:
    return await self._post(f"/payments/{payment_id}/refund", json={})
```

- [ ] **Step 4: Run client tests and Ruff**

Run: `pytest tests/test_asaas_client.py -v`

Run: `ruff check app/services/asaas_client.py tests/test_asaas_client.py`

- [ ] **Step 5: Commit**

```text
git add app/services/asaas_client.py app/config.py .env.example .env.prod.example tests/test_asaas_client.py
git commit -m "fix: make Asaas requests safe and traceable"
```

### Task 4: Customer and charge reconciliation

**Files:**
- Modify: `app/services/payment_service.py`
- Modify: `app/api/payments.py`
- Create: `tests/test_payment_reconciliation.py`

**Interfaces:**
- Consumes: Task 3 client methods and exceptions.
- Produces: `PaymentService.ensure_asaas_customer(user_id: int) -> str` with remote reconciliation.
- Produces: `PaymentService.create_charge(...) -> Payment` with appointment-level locking and remote reconciliation.

- [ ] **Step 1: Write failing reconciliation tests**

```python
def test_charge_reuses_remote_match_after_uncertain_create(db_session):
    service, appointment = payment_service_with_appointment(db_session)
    service.asaas.create_payment = AsyncMock(side_effect=AsaasUncertainResultError("timeout"))
    service.asaas.list_payments = AsyncMock(return_value=[asaas_payment("pay_recovered")])
    payment = asyncio.run(service.create_charge(appointment.id, "pix"))
    assert payment.asaas_payment_id == "pay_recovered"
    assert service.asaas.create_payment.await_count == 1

def test_charge_refuses_multiple_remote_matches(db_session):
    service, appointment = payment_service_with_appointment(db_session)
    service.asaas.list_payments = AsyncMock(return_value=[asaas_payment("pay_1"), asaas_payment("pay_2")])
    with pytest.raises(AsaasReconciliationError):
        asyncio.run(service.create_charge(appointment.id, "pix"))
```

- [ ] **Step 2: Verify both tests fail with current non-reconciling service**

Run: `pytest tests/test_payment_reconciliation.py -v`

- [ ] **Step 3: Implement deterministic reconciliation**

Lock the appointment row with `with_for_update()` on PostgreSQL. Reuse local active payment first. Search remote by `appointment:{id}` before create and once after an uncertain result. Persist exactly one result through a helper:

```python
def _payment_from_asaas(self, appointment: Appointment, payload: dict, billing_type: str) -> Payment:
    return Payment(
        appointment_id=appointment.id,
        asaas_payment_id=payload["id"],
        amount_cents=appointment.service.price_cents,
        billing_type=billing_type,
        status=ASAAS_STATUS_MAP.get(payload.get("status"), "pending"),
        invoice_url=payload.get("invoiceUrl"),
    )
```

Use the equivalent `user:{id}` flow for customers. Do not commit midway through the local payment/appointment update.

- [ ] **Step 4: Run payment tests**

Run: `pytest tests/test_payment_reconciliation.py tests/test_flow_completo.py::TestFluxoCompleto::test_criacao_de_cobranca_e_idempotente -v`

- [ ] **Step 5: Commit**

```text
git add app/services/payment_service.py app/api/payments.py tests/test_payment_reconciliation.py
git commit -m "fix: reconcile Asaas customers and charges"
```

### Task 5: Transactional webhook state transitions

**Files:**
- Create: `app/services/payment_state_service.py`
- Modify: `app/api/webhooks.py`
- Modify: `app/services/payment_service.py`
- Modify: `tests/test_flow_completo.py`
- Create: `tests/test_webhook_states.py`

**Interfaces:**
- Produces: `apply_payment_state(payment: Payment, new_status: str, now: datetime) -> None`.
- Consumes: the helper from both webhook and manual refresh paths.

- [ ] **Step 1: Add failing provider-ID and transition tests**

```python
def test_webhook_deduplicates_by_provider_event_id(client, db_session):
    payment = seeded_payment(db_session)
    payload = {"id": "evt_1", "event": "PAYMENT_RECEIVED", "payment": {"id": payment.asaas_payment_id}}
    assert post_webhook(client, payload).json()["status"] == "ok"
    assert post_webhook(client, payload).json()["reason"] == "duplicate"

def test_different_events_of_same_type_are_recorded(client, db_session):
    payment = seeded_payment(db_session)
    first = webhook_payload("evt_1", "PAYMENT_CONFIRMED", payment)
    second = webhook_payload("evt_2", "PAYMENT_CONFIRMED", payment)
    assert post_webhook(client, first).json()["status"] == "ok"
    assert post_webhook(client, second).json()["status"] == "ok"

def test_late_payment_does_not_reactivate_cancelled_appointment(client, db_session):
    appointment, payment = seeded_cancelled_appointment_payment(db_session)
    post_webhook(client, webhook_payload("evt_late", "PAYMENT_RECEIVED", payment))
    db_session.refresh(appointment)
    assert appointment.status == "cancelled"
```

- [ ] **Step 2: Run and observe synthetic-ID collision and late reactivation failures**

Run: `pytest tests/test_webhook_states.py -v`

- [ ] **Step 3: Implement provider-event idempotency and shared transitions**

Use `body["id"]` or a SHA-256 canonical JSON fallback. Always commit the event row, including unchanged/unknown events. `apply_payment_state` follows the exact transition table in the spec and never confirms a cancelled, completed, or expired appointment.

- [ ] **Step 4: Run webhook and payment status tests**

Run: `pytest tests/test_webhook_states.py tests/test_flow_completo.py -v`

- [ ] **Step 5: Commit**

```text
git add app/api/webhooks.py app/services/payment_service.py app/services/payment_state_service.py tests
git commit -m "fix: make payment webhooks transactional"
```

### Task 6: Real refresh and refund operations

**Files:**
- Modify: `app/services/payment_service.py`
- Modify: `app/admin/router.py`
- Modify: `app/admin/service.py`
- Modify: `app/admin/schemas.py`
- Modify: `hermes/profiles/financeiro.yaml`
- Create: `tests/test_admin_payments.py`

**Interfaces:**
- Produces: `PaymentService.refresh(payment_id: int) -> Payment`.
- Produces: `PaymentService.refund(payment_id: int) -> Payment`.

- [ ] **Step 1: Write failing admin-payment tests**

```python
def test_admin_refund_calls_asaas_before_local_change(admin_client, db_session, monkeypatch):
    payment = seeded_received_payment(db_session)
    refund = AsyncMock(return_value={"id": payment.asaas_payment_id, "status": "REFUNDED"})
    monkeypatch.setattr(AsaasClient, "refund_payment", refund)
    response = admin_client.post(f"/admin/payments/{payment.id}/action", json={"action": "refund"})
    assert response.status_code == 200
    assert refund.await_count == 1
    db_session.refresh(payment)
    assert payment.status == "refunded"

def test_failed_asaas_refund_keeps_local_status(admin_client, db_session, monkeypatch):
    payment = seeded_received_payment(db_session)
    monkeypatch.setattr(AsaasClient, "refund_payment", AsyncMock(side_effect=AsaasIntegrationError("rejected")))
    response = admin_client.post(f"/admin/payments/{payment.id}/action", json={"action": "refund"})
    assert response.status_code == 502
    db_session.refresh(payment)
    assert payment.status == "received"
```

- [ ] **Step 2: Verify the first test shows a fake local-only refund and the second cannot be handled safely**

Run: `pytest tests/test_admin_payments.py -v`

- [ ] **Step 3: Implement asynchronous refresh/refund through `PaymentService`**

The route awaits `refresh` or `refund`. Refund validates local status and Asaas ID, awaits Asaas, then applies `refunded` state and commits. Remove the local-only branches from `AdminService`. Remove the three-minute payment polling job from `financeiro.yaml`.

- [ ] **Step 4: Run admin, payment, and full Package 1 tests**

Run: `pytest tests/test_authentication.py tests/test_asaas_client.py tests/test_payment_reconciliation.py tests/test_webhook_states.py tests/test_admin_payments.py tests/test_flow_completo.py tests/test_mcp_clientes.py -v`

Run: `ruff check app tests`

- [ ] **Step 5: Commit**

```text
git add app/services/payment_service.py app/admin app/services/payment_state_service.py hermes/profiles/financeiro.yaml tests
git commit -m "fix: synchronize admin payment operations with Asaas"
```
