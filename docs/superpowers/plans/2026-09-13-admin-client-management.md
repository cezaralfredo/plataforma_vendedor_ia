# Admin Client Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Disponibilizar gestão administrativa completa de clientes sem comprometer histórico de agendamentos e pagamentos.

**Architecture:** Criar rotas e schemas administrativos próprios sobre o modelo `User`. Adicionar `active` ao cliente para arquivamento seguro, oferecer consulta paginada com resumo histórico e reutilizar a mesma fonte de clientes no novo agendamento.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, Pydantic, Jinja2, Alpine.js, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-admin-quality-hardening-design.md`

## Global Constraints

- Cliente com vínculo histórico é arquivado, não apagado.
- Exclusão definitiva só é permitida sem agendamentos e sem pagamentos relacionados.
- CPF/CNPJ e identificador Asaas não aparecem na listagem resumida.
- Todas as mutações exigem sessão administrativa e CSRF.

---

### Task 1: Estado de arquivamento e regras de ciclo de vida

**Files:**
- Create: `alembic/versions/a4c7e2f9b1d6_add_user_active.py`
- Modify: `app/models/user.py`
- Modify: `app/admin/service.py`
- Test: `tests/test_admin_clients.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces: `User.active: bool`, non-null, server default `true`.
- Produces: `AdminService.archive_or_delete_user(user_id: int) -> Literal['archived', 'deleted']`.
- Produces: `AdminService.reactivate_user(user_id: int) -> User`.

- [ ] **Step 1: Write failing lifecycle tests**

```python
assert service.archive_or_delete_user(unlinked.id) == 'deleted'
assert service.archive_or_delete_user(linked.id) == 'archived'
assert service.get_user(linked.id).active is False
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_clients.py -k lifecycle -v`
Expected: FAIL because `active` and lifecycle methods do not exist.

- [ ] **Step 3: Add the model field, migration and transactional rules**

```python
active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
```

Count appointments before deletion. Archive when count is non-zero; delete only when no relationship exists. Convert integrity failures to a domain conflict after rollback.

- [ ] **Step 4: Verify lifecycle and migration tests**

Run: `pytest tests/test_admin_clients.py tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions app/models/user.py app/admin/service.py tests/test_admin_clients.py tests/test_migrations.py
git commit -m "feat(admin): protect client history with archiving"
```

### Task 2: Administrative client API and summaries

**Files:**
- Modify: `app/admin/schemas.py`
- Modify: `app/admin/router.py`
- Modify: `app/admin/service.py`
- Test: `tests/test_admin_clients.py`
- Test: `tests/test_admin_csrf.py`

**Interfaces:**
- Produces: `GET /admin/api/clients?page=&page_size=&search=&status=`.
- Produces: `POST /admin/api/clients`, `PUT /admin/api/clients/{id}`, `DELETE /admin/api/clients/{id}`, `POST /admin/api/clients/{id}/reactivate`.
- Client item fields: `id`, `name`, `phone`, `email`, `active`, `appointments_total`, `payments_received_total`, `last_appointment_at`.

- [ ] **Step 1: Write failing CRUD, pagination and CSRF tests**

```python
response = client.get('/admin/api/clients?page=1&page_size=20', headers=admin_headers)
assert response.json()['data'][0]['appointments_total'] == 1
assert response.json()['data'][0]['payments_received_total'] == 1
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_clients.py tests/test_admin_csrf.py -k clients -v`
Expected: FAIL with 404 for the new API.

- [ ] **Step 3: Implement schemas, joined aggregate query and mutation routes**

Use correlated aggregate subqueries or grouped outer joins so the endpoint does not issue one query per client. Translate unique phone/email conflicts into HTTP 409 with a human-readable detail.

- [ ] **Step 4: Verify API, authorization and query-count behavior**

Run: `pytest tests/test_admin_clients.py tests/test_admin_csrf.py -k clients -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/admin/schemas.py app/admin/router.py app/admin/service.py tests/test_admin_clients.py tests/test_admin_csrf.py
git commit -m "feat(admin): add protected client management API"
```

### Task 3: Client management page

**Files:**
- Replace: `app/admin/templates/users.html`
- Delete: `app/admin/templates/admins.html`
- Delete: `app/admin/templates/availability.html`
- Modify: `app/admin/templates/base.html`
- Modify: `app/admin/router.py`
- Test: `tests/test_admin_clients.py`
- Test: `tests/test_admin_responsive_markup.py`

**Interfaces:**
- Produces page: `GET /admin/clients`.
- Consumes the API from Task 2 and shared dialog/notification utilities from the UX plan.

- [ ] **Step 1: Write failing page tests**

```python
assert client.get('/admin/clients', headers=admin_headers).status_code == 200
assert 'Clientes' in page.text
assert '/admin/clients' in base_navigation
assert 'admin-mobile-list md:hidden' in page.text
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_clients.py tests/test_admin_responsive_markup.py -k clients -v`
Expected: FAIL because the route and menu item are absent.

- [ ] **Step 3: Build list, filters, summary, create/edit modal and history summary**

Do not show CPF/CNPJ or Asaas id in the list. Show full contact only in the edit/detail modal. Use `Arquivar`, `Excluir` or `Reativar` based on current state and server result. Remove the unreachable `admins.html` and `availability.html`; professional availability remains managed by `professional_detail.html`.

- [ ] **Step 4: Verify rendering, script and mobile tests**

Run: `pytest tests/test_admin_clients.py tests/test_admin_responsive_markup.py tests/test_admin_csrf.py -k clients -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/admin/templates/users.html app/admin/templates/admins.html app/admin/templates/availability.html app/admin/templates/base.html app/admin/router.py tests/test_admin_clients.py tests/test_admin_responsive_markup.py tests/test_admin_csrf.py
git commit -m "feat(admin): add client management workspace"
```

### Task 4: Reuse client catalog in new appointments

**Files:**
- Modify: `app/admin/service.py`
- Modify: `app/admin/router.py`
- Modify: `app/admin/templates/appointments.html`
- Modify: `app/repositories/user_repo.py`
- Modify: `app/services/user_service.py`
- Test: `tests/test_admin_appointments_management.py`
- Test: `tests/test_admin_clients.py`
- Test: `tests/test_mcp_clientes.py`

**Interfaces:**
- Consumes: active clients from Task 2.
- Produces appointment option items `clients: [{id, name, masked_phone}]`, rejects archived clients for new appointments and excludes archived clients from public/MCP active-client lookup without hiding their administrative history.

- [ ] **Step 1: Write failing option and validation tests**

```python
assert active.name in response.text
assert archived.name not in response.text
assert create_with_archived_client.status_code == 409
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_admin_appointments_management.py -k client -v`
Expected: FAIL because archived-state filtering is not implemented.

- [ ] **Step 3: Use one client source for selection and creation**

Return active clients in the appointment options, keep inline new-client creation, and refresh/select the created client after successful creation. Centralize the active-client predicate in `UserRepository` so public, MCP and admin scheduling flows cannot diverge.

- [ ] **Step 4: Verify appointment and client regressions**

Run: `pytest tests/test_admin_appointments_management.py tests/test_admin_clients.py tests/test_mcp_clientes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/admin/service.py app/admin/router.py app/admin/templates/appointments.html app/repositories/user_repo.py app/services/user_service.py tests/test_admin_appointments_management.py tests/test_admin_clients.py tests/test_mcp_clientes.py
git commit -m "feat(admin): share clients with appointment creation"
```
