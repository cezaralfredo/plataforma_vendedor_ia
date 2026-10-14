# Admin Operational Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir valores técnicos, carregamentos ambíguos, requisições redundantes, sincronização financeira e falsos positivos do catálogo.

**Architecture:** Manter FastAPI, Jinja e Alpine existentes. Normalizar valores somente na camada administrativa, introduzir estado explícito de requisição em cada página e preservar os valores técnicos na API pública e no banco.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Jinja2, Alpine.js, pytest, Node.js para testes dos scripts renderizados.

**Spec:** `docs/superpowers/specs/2026-09-12-admin-quality-hardening-design.md`

## Global Constraints

- Nenhuma correção de código apagará ou renomeará dados de produção automaticamente.
- Todas as mutações administrativas continuam protegidas por sessão e CSRF.
- O catálogo permanece pertencente à empresa; preço e duração não migram para o profissional.
- Cada tarefa termina com os testes focados e a suíte oficial no CI com Python 3.11.

---

### Task 1: Valores de pagamento legíveis

**Files:**
- Modify: `app/admin/templates/payments.html`
- Modify: `app/admin/templates/appointment_detail.html`
- Test: `tests/test_admin_csrf.py`
- Test: `tests/test_admin_payments.py`

**Interfaces:**
- Consumes: `Payment.billing_type: str | None` da resposta administrativa.
- Produces: `formatBillingType(value: string | null): string`, com `undefined`/ausente → `A definir`, `pix` → `PIX`, `boleto` → `Boleto`, `credit_card` → `Cartão de crédito`.

- [ ] **Step 1: Write the failing JavaScript assertions**

```python
result = run_page_javascript(page.text, """
    const ui = payments();
    assert.equal(ui.formatBillingType('undefined'), 'A definir');
    assert.equal(ui.formatBillingType(null), 'A definir');
    assert.equal(ui.formatBillingType('pix'), 'PIX');
    assert.equal(ui.formatBillingType('credit_card'), 'Cartão de crédito');
""")
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `pytest tests/test_admin_csrf.py -k billing_type -v`
Expected: FAIL because `formatBillingType` is not defined.

- [ ] **Step 3: Implement presentation-only normalization**

```javascript
formatBillingType(value) {
    return {
        undefined: 'A definir',
        pix: 'PIX',
        boleto: 'Boleto',
        credit_card: 'Cartão de crédito'
    }[value] || 'A definir';
}
```

Use the function in the payment table and appointment detail instead of rendering `billing_type` directly.

- [ ] **Step 4: Verify focused and related tests**

Run: `pytest tests/test_admin_csrf.py tests/test_admin_payments.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/admin/templates/payments.html app/admin/templates/appointment_detail.html tests/test_admin_csrf.py tests/test_admin_payments.py
git commit -m "fix(admin): present payment methods clearly"
```

### Task 2: Estados explícitos de carregamento e falha

**Files:**
- Modify: `app/admin/templates/dashboard.html`
- Modify: `app/admin/templates/appointments.html`
- Modify: `app/admin/templates/payments.html`
- Modify: `app/admin/templates/professionals.html`
- Test: `tests/test_admin_csrf.py`
- Create: `tests/test_admin_pages.py`

**Interfaces:**
- Produces per page: `loading: boolean`, `loadError: string`, `reload(): Promise<void>`.
- Produces copy: `Não foi possível carregar os dados. Tente novamente.` and a `Tentar novamente` button.

- [ ] **Step 1: Add failing render and JavaScript tests**

```python
assert 'Tentar novamente' in response.text
result = run_page_javascript(response.text, """
    const page = dashboard();
    await page.loadKPIs();
    assert.equal(page.loadError, 'Não foi possível carregar os dados. Tente novamente.');
""", ok=False, status=503)
```

- [ ] **Step 2: Verify the tests fail on the current empty/error ambiguity**

Run: `pytest tests/test_admin_csrf.py tests/test_admin_pages.py -k "load or retry" -v`
Expected: FAIL because pages do not expose `loadError` and retry controls.

- [ ] **Step 3: Add page-local request state**

```javascript
async reload() {
    this.loading = true;
    this.loadError = '';
    try {
        await this.loadData();
    } catch (_error) {
        this.loadError = 'Não foi possível carregar os dados. Tente novamente.';
    } finally {
        this.loading = false;
    }
}
```

Ensure every `adminFetch` checks `response.ok` before parsing JSON. Render skeleton/loading, error/retry and true empty state as mutually exclusive regions.

- [ ] **Step 4: Verify focused tests and all admin JavaScript tests**

Run: `pytest tests/test_admin_csrf.py tests/test_admin_pages.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/admin/templates/dashboard.html app/admin/templates/appointments.html app/admin/templates/payments.html app/admin/templates/professionals.html tests/test_admin_csrf.py tests/test_admin_pages.py
git commit -m "fix(admin): distinguish loading failure and empty data"
```

### Task 3: Estado real das integrações no Dashboard

**Files:**
- Modify: `app/admin/schemas.py`
- Modify: `app/admin/service.py`
- Modify: `app/admin/router.py`
- Modify: `app/admin/templates/dashboard.html`
- Test: `tests/test_admin_system_status.py`

**Interfaces:**
- Produces: `GET /admin/api/system-status` returning `api`, `database`, `asaas` and `mcp` objects.
- `asaas` reports configuration and environment inferred from the configured base URL; it does not claim remote availability without a remote probe.
- `mcp` reports `endpoint_enabled`; it does not claim Hermes is connected.

- [ ] **Step 1: Write failing status semantics tests**

```python
payload = client.get('/admin/api/system-status', headers=admin_headers).json()
assert payload['api'] == {'status': 'online'}
assert payload['database'] == {'status': 'connected'}
assert payload['asaas']['mode'] in {'sandbox', 'production'}
assert payload['mcp'] == {'endpoint_enabled': True}
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_system_status.py -v`
Expected: FAIL with 404 for `/admin/api/system-status`.

- [ ] **Step 3: Implement truthful status reporting**

Run a lightweight `SELECT 1` for the database, derive the Asaas mode from `settings.asaas_base_url`, and report only that the MCP endpoint is enabled. Replace static claims such as `Hermes/MCP Disponível` with the returned semantics.

- [ ] **Step 4: Verify status and dashboard tests**

Run: `pytest tests/test_admin_system_status.py tests/test_admin_pages.py -k "status or dashboard" -v`
Expected: PASS, including a simulated database failure rendered as unavailable.

- [ ] **Step 5: Commit**

```bash
git add app/admin/schemas.py app/admin/service.py app/admin/router.py app/admin/templates/dashboard.html tests/test_admin_system_status.py
git commit -m "fix(admin): report integration status truthfully"
```

### Task 4: Consulta de profissionais sem requisição redundante

**Files:**
- Modify: `app/admin/templates/professionals.html`
- Modify: `app/admin/templates/appointments.html`
- Test: `tests/test_admin_csrf.py`

**Interfaces:**
- Consumes: `GET /admin/api/professionals`.
- Produces: exatamente uma consulta JSON por carregamento da lista de profissionais.

- [ ] **Step 1: Tighten the JavaScript call-count assertions**

```python
result = run_page_javascript(page.text, "const page = professionals(); await page.loadProfessionals();")
assert [call["url"] for call in result["calls"]] == ["/admin/api/professionals"]
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_csrf.py -k professionals -v`
Expected: FAIL because `/admin/professionals` is fetched before the API.

- [ ] **Step 3: Remove the HTML fetch and dead parser comments**

```javascript
async loadProfessionals() {
    const response = await adminFetch('/admin/api/professionals');
    if (!response.ok) throw new Error('professionals-load-failed');
    this.professionals = await response.json();
}
```

Use the same endpoint to populate the appointment filter where required.

- [ ] **Step 4: Verify the focused tests**

Run: `pytest tests/test_admin_csrf.py -k professionals -v`
Expected: PASS with one API call per load.

- [ ] **Step 5: Commit**

```bash
git add app/admin/templates/professionals.html app/admin/templates/appointments.html tests/test_admin_csrf.py
git commit -m "perf(admin): remove redundant professionals request"
```

### Task 5: Sincronização financeira verificável

**Files:**
- Modify: `app/admin/router.py`
- Modify: `app/admin/templates/payments.html`
- Modify: `app/admin/templates/appointment_detail.html`
- Modify: `app/admin/schemas.py`
- Test: `tests/test_admin_payments.py`
- Test: `tests/test_admin_csrf.py`

**Interfaces:**
- Produces: `PaymentActionResult { message: str, changed: bool, payment: AdminPayment }`.
- UI state: `syncingPaymentId: number | null` and notice containing the returned status.

- [ ] **Step 1: Add failing route tests for changed and unchanged synchronization**

```python
assert response.json() == {
    "message": "Pagamento sincronizado: vencido.",
    "changed": True,
    "payment": expected_payment,
}
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_payments.py -k refresh -v`
Expected: FAIL because the route does not return `changed` and the normalized payment payload.

- [ ] **Step 3: Return a structured action result and update one row**

```javascript
const result = await response.json();
const index = this.payments.findIndex(item => item.id === id);
if (index >= 0) this.payments[index] = result.payment;
this.notice = result.message;
```

Disable only the active synchronization button and clear it in `finally`.

- [ ] **Step 4: Verify route and JavaScript behavior**

Run: `pytest tests/test_admin_payments.py tests/test_admin_csrf.py -k "payment or refresh" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/admin/router.py app/admin/schemas.py app/admin/templates/payments.html app/admin/templates/appointment_detail.html tests/test_admin_payments.py tests/test_admin_csrf.py
git commit -m "fix(admin): report payment synchronization outcome"
```

### Task 6: Diagnóstico comercial de serviços semelhantes

**Files:**
- Modify: `app/admin/service.py`
- Modify: `app/admin/templates/services.html`
- Test: `tests/test_admin_services_page.py`

**Interfaces:**
- Produces issue kinds: `duplicate` only when normalized name, category, price and duration match; `similar_name` when only normalized name matches.
- No automatic data mutation.

- [ ] **Step 1: Add failing catalog cases**

```python
assert dashboard["issues"] == [{
    "kind": "similar_name",
    "label": "Corte de cabelo",
    "service_ids": [masculino.id, feminino.id],
}]
```

Also assert exact commercial duplicates remain `duplicate`.

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_services_page.py -k "duplicate or similar" -v`
Expected: FAIL because all equal names are classified as duplicates.

- [ ] **Step 3: Group by commercial identity**

```python
identity = (
    normalize(service.name),
    normalize(service.category or ""),
    service.price_cents,
    service.duration_minutes,
)
```

Render `Nomes semelhantes — confira a denominação` separately from `Possível duplicidade`.

- [ ] **Step 4: Verify catalog and regression tests**

Run: `pytest tests/test_admin_services_page.py tests/test_company_service_catalog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/admin/service.py app/admin/templates/services.html tests/test_admin_services_page.py
git commit -m "fix(admin): distinguish similar services from duplicates"
```

### Task 7: Release 1 verification

**Files:**
- Modify: `docs/superpowers/plans/2026-09-13-admin-operational-correctness.md`

**Interfaces:**
- Produces: a releasable correction set independent from later plans.

- [ ] **Step 1: Run static checks**

Run: `ruff check app tests`
Expected: PASS.

- [ ] **Step 2: Run the full suite in the supported environment**

Run: `pytest -q` under Python 3.11.
Expected: all tests PASS.

- [ ] **Step 3: Validate formatting and scope**

Run: `git diff --check origin/master...HEAD`
Expected: no whitespace errors.

- [ ] **Step 4: Commit plan progress only if checkbox state changed**

```bash
git add docs/superpowers/plans/2026-09-13-admin-operational-correctness.md
git commit -m "docs: record operational correctness verification"
```
