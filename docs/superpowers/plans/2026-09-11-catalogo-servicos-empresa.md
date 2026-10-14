# Catálogo de Serviços da Empresa Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar os serviços em catálogo único da empresa, habilitando profissionais por serviço e confirmando horários somente após pagamento aprovado.

**Architecture:** `services` armazena a oferta comercial da empresa; `professional_services` registra a capacidade de execução, comissão e estado para cada profissional. APIs, agenda e painel consultam uma habilitação ativa; somente pagamentos aprovados confirmam reservas.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, PostgreSQL, Jinja2, Alpine.js e pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-catalogo-servicos-empresa-design.md`

## Global Constraints

- O catálogo é global: preço, duração, descrição e categoria pertencem à empresa.
- A comissão pertence à associação, inicia em 10,00% e aceita de 0,00 a 100,00%.
- Agendamento e confirmação exigem profissional ativo e habilitação ativa.
- Só pagamentos `received` ou `confirmed` confirmam reservas; `overdue` e `cancelled` as liberam.
- Exclusão definitiva só é permitida sem histórico financeiro nem agenda confirmada/concluída.
- A migração preserva agendamentos e pagamentos, consolida somente serviços exatamente equivalentes e executa em PostgreSQL.
- Não incluir no commit os arquivos que já estavam alterados fora deste trabalho.

---

## Estrutura de arquivos

- `app/models/service.py`: catálogo sem `professional_id`, com estado ativo.
- `app/models/professional_service.py`: associação, comissão e estado de habilitação.
- `app/models/professional.py`, `app/models/__init__.py`: relacionamentos e exportação.
- `alembic/versions/<revision>_company_service_catalog.py`: estrutura e migração de dados legados.
- `app/schemas/service.py`, `app/schemas/professional_service.py`: contratos do catálogo e da habilitação.
- `app/repositories/professional_service_repo.py`, `app/services/professional_service.py`, `app/api/professional_services.py`: acesso e gestão das relações.
- `app/services/service_service.py`: gestão e exclusão segura do catálogo.
- `app/services/appointment_service.py`, `app/services/availability_service.py`, `app/services/payment_state_service.py`: regras de habilitação e pagamento.
- `app/admin/service.py`, `app/admin/router.py`, `app/admin/templates/services.html`, `app/admin/templates/professionals.html`: painel.
- `tests/test_service_catalog.py`, `tests/test_professional_service.py`, `tests/test_catalog_migration.py`, `tests/test_admin_services.py`: cobertura nova.

## Task 1: Modelo, contratos e fixture do catálogo

**Files:**
- Create: `app/models/professional_service.py`, `app/schemas/professional_service.py`, `tests/test_service_catalog.py`
- Modify: `app/models/service.py`, `app/models/professional.py`, `app/models/__init__.py`, `app/schemas/service.py`, `tests/seed.py`

**Interfaces:**
- Produces: `ProfessionalService(professional_id, service_id, commission_percent=Decimal("10.00"), active=True)`.
- Produces: `ServiceCreate(name, duration_minutes, price_cents, description=None, category=None, active=True)`.
- Produces: `ProfessionalServiceCreate(service_id: int, commission_percent: Decimal = Decimal("10.00"), active: bool = True)`.

- [ ] **Step 1: Write the failing test**

```python
def test_service_is_company_catalog_and_link_defaults_to_ten_percent(db_session):
    service = Service(name="Corte feminino", duration_minutes=60, price_cents=9000)
    professional = Professional(name="Ana", active=True)
    db_session.add_all([service, professional])
    db_session.flush()

    link = ProfessionalService(professional_id=professional.id, service_id=service.id)
    db_session.add(link)
    db_session.commit()

    assert service.active is True
    assert link.commission_percent == Decimal("10.00")
    assert not hasattr(service, "professional_id")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_service_catalog.py::test_service_is_company_catalog_and_link_defaults_to_ten_percent -v`

Expected: FAIL because the association and catalog-only Service do not exist.

- [ ] **Step 3: Write the minimal implementation**

```python
class ProfessionalService(Base):
    __tablename__ = "professional_services"
    __table_args__ = (
        UniqueConstraint("professional_id", "service_id", name="uq_professional_services_pair"),
        CheckConstraint("commission_percent >= 0 AND commission_percent <= 100", name="check_commission_percent"),
    )
    commission_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="10.00")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

Remove `Service.professional_id`; add `Service.active`, `Service.professional_services`, `Professional.service_assignments` and Pydantic validation for commission.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_service_catalog.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models app/schemas tests/seed.py tests/test_service_catalog.py
git commit -m "feat: model company service catalog"
```

## Task 2: Migração PostgreSQL e preservação de dados

**Files:**
- Create: `alembic/versions/<revision>_company_service_catalog.py`, `tests/test_catalog_migration.py`
- Modify: `alembic/versions/4a6f9d2e1b3c_enforce_scheduling_invariants.py` somente se necessário para substituir uma constraint.

**Interfaces:**
- Consumes: serviços legados com `professional_id` e agendamentos que os referenciam.
- Produces: `professional_services`, catálogo consolidado e todos os `appointments.service_id` preservados.

- [ ] **Step 1: Write the failing migration test**

```python
@pytest.mark.postgres
def test_catalog_migration_merges_exact_duplicates_and_preserves_appointments(alembic_engine):
    seed_legacy_duplicate_services(alembic_engine)
    upgrade_to_head(alembic_engine)

    assert count_rows(alembic_engine, "services") == 1
    assert count_rows(alembic_engine, "professional_services") == 2
    assert all_appointments_reference_catalog_service(alembic_engine)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -m postgres tests/test_catalog_migration.py::test_catalog_migration_merges_exact_duplicates_and_preserves_appointments -v`

Expected: FAIL because the revision and association table do not exist.

- [ ] **Step 3: Write the migration**

Create the association table. Group legacy rows by exact `(name, description, category, duration_minutes, price_cents)`; retain the lowest ID in each group; update appointments from duplicate IDs to that canonical ID; insert each legacy professional/canonical pair with commission `10.00`; delete duplicate rows; add `services.active`; remove the old foreign key/index and drop `services.professional_id`. Do not merge rows with any divergent commercial field.

- [ ] **Step 4: Run migration verification**

Run: `pytest -m postgres tests/test_catalog_migration.py -v && alembic upgrade head`

Expected: PASS; all paid appointment references remain valid.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions tests/test_catalog_migration.py
git commit -m "feat: migrate services to company catalog"
```

## Task 3: Gestão do catálogo, habilitações e exclusão segura

**Files:**
- Create: `app/repositories/professional_service_repo.py`, `app/services/professional_service.py`, `app/api/professional_services.py`, `tests/test_professional_service.py`
- Modify: `app/repositories/__init__.py`, `app/repositories/service_repo.py`, `app/services/__init__.py`, `app/services/service_service.py`, `app/api/services.py`, `app/main.py`

**Interfaces:**
- Produces: `ProfessionalServiceService.assign(professional_id, data)`, `update(assignment_id, data)`, `remove(assignment_id)`, `is_active_assignment(professional_id, service_id) -> bool`.
- Produces: `ServiceService.delete(service_id) -> bool` that removes only expired/unpaid dependents or raises `RelatedRecordsError`.

- [ ] **Step 1: Write the failing tests**

```python
def test_catalog_service_is_shared_with_individual_commissions(client):
    service = create_catalog_service(client, "Corte feminino")
    ana, bia = create_two_professionals(client)
    assign(client, ana["id"], service["id"], "10.00")
    assign(client, bia["id"], service["id"], "25.00")

    assert listed_services(client, ana["id"])[0]["id"] == service["id"]
    assert listed_services(client, bia["id"])[0]["commission_percent"] == "25.00"
```

```python
def test_delete_service_removes_only_expired_unpaid_reservations(client, db_session):
    service, appointment = create_expired_unpaid_service_history(db_session)
    assert client.delete(f"/api/services/{service.id}").status_code == 204
    assert db_session.get(Appointment, appointment.id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_professional_service.py tests/test_service_catalog.py -v`

Expected: FAIL because assignment endpoints and safe deletion do not exist.

- [ ] **Step 3: Write the minimal implementation**

Add protected routes under `/api/professionals/{professional_id}/services`. Query service lists through active catalog/assignment joins. In `ServiceService.delete`, allow removal only if every dependent appointment is cancelled/expired and every payment is absent, pending, overdue or cancelled; delete notification logs, payments, appointments, assignments and then the service. Reject any received/confirmed payment or confirmed/completed appointment with the instruction to deactivate the service.

- [ ] **Step 4: Run targeted tests**

Run: `pytest tests/test_professional_service.py tests/test_service_catalog.py tests/test_crud_integrity.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/repositories app/services app/api app/main.py tests/test_professional_service.py tests/test_service_catalog.py
git commit -m "feat: manage professional service assignments"
```

## Task 4: Reserva condicionada a pagamento

**Files:**
- Modify: `app/services/appointment_service.py`, `app/services/availability_service.py`, `app/services/payment_state_service.py`, `app/services/payment_service.py`, `app/repositories/appointment_repo.py`
- Modify: `tests/test_appointment_lifecycle.py`, `tests/test_payment_reconciliation.py`, `tests/test_webhook_states.py`

**Interfaces:**
- Consumes: `ProfessionalServiceService.is_active_assignment(professional_id, service_id)`.
- Produces: criação/slots rejeitando profissional não habilitado e `AppointmentService.confirm()` aceitando somente pagamento aprovado.

- [ ] **Step 1: Write the failing tests**

```python
def test_cannot_confirm_appointment_before_payment_is_approved(db_session):
    appointment = seed_appointment(db_session, seed_catalog_data(db_session))
    payment = seed_payment(db_session, appointment)

    with pytest.raises(ValueError, match="pagamento aprovado"):
        AppointmentService(db_session).confirm(appointment.id)

    apply_payment_state(payment, "confirmed", datetime.now(UTC))
    assert AppointmentService(db_session).confirm(appointment.id).status == "confirmed"
```

```python
def test_slots_are_empty_for_unassigned_professional_service_pair(db_session):
    assert AvailabilityService(db_session).get_time_slots_for_service(unassigned_professional_id, service_id, "2026-07-30") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_appointment_lifecycle.py tests/test_webhook_states.py -v`

Expected: FAIL because manual confirmation bypasses payment and slots read `service.professional_id`.

- [ ] **Step 3: Write the minimal implementation**

Replace every `service.professional_id` comparison with an active-assignment check. Keep reservation status as `awaiting_payment` after charge creation. Permit confirmation only if a related payment is `received` or `confirmed`. On `overdue` or `cancelled`, cancel the reservation and release the time window, retaining the existing overlap constraint.

- [ ] **Step 4: Run lifecycle and payment tests**

Run: `pytest tests/test_appointment_lifecycle.py tests/test_payment_reconciliation.py tests/test_webhook_states.py tests/test_business_time.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services app/repositories/appointment_repo.py tests/test_appointment_lifecycle.py tests/test_payment_reconciliation.py tests/test_webhook_states.py
git commit -m "fix: confirm appointments only after payment"
```

## Task 5: Painel administrativo do catálogo

**Files:**
- Create: `app/admin/templates/services.html`, `tests/test_admin_services.py`
- Modify: `app/admin/service.py`, `app/admin/router.py`, `app/admin/templates/base.html`, `app/admin/templates/professionals.html`, `tests/test_admin_queries.py`

**Interfaces:**
- Produces: `AdminService.list_services()` with `id, name, category, duration_minutes, price_cents, active, professionals_count`.
- Produces: protected `GET /admin/services` and `GET /admin/api/services`.

- [ ] **Step 1: Write the failing admin test**

```python
def test_admin_services_lists_catalog_once_with_enabled_professional_count(admin_client, db_session):
    service, _ = seed_catalog_with_two_professionals(db_session)
    response = admin_client.get("/admin/services")

    assert response.status_code == 200
    assert response.text.count(service.name) == 1
    assert "2 profissionais" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_admin_services.py::test_admin_services_lists_catalog_once_with_enabled_professional_count -v`

Expected: FAIL because the services view and admin query do not exist.

- [ ] **Step 3: Write the minimal implementation**

Add Serviços to the sidebar and render one row per catalog item: category, duration, price, active badge, enabled-professional count and actions to edit, deactivate/reactivate and delete. In Profissionais, replace service creation with selection of a catalog service and an individual commission field. Show the API error next to the affected action.

- [ ] **Step 4: Run panel and full tests**

Run: `pytest tests/test_admin_services.py tests/test_admin_queries.py -v && pytest -q`

Expected: PASS.

- [ ] **Step 5: Run checks and commit**

Run: `ruff check app tests && python -m compileall app`

Expected: exit code 0 for both commands.

```bash
git add app/admin tests/test_admin_services.py tests/test_admin_queries.py
git commit -m "feat: add company services admin panel"
```

## Task 6: Publicação e validação de produção

**Files:**
- Modify: `README.md` only if its endpoint list is maintained.
- Test: `tests/test_deployment_config.py` and checks in Portainer.

**Interfaces:**
- Produces: migration executed on startup, catalogue available at `/admin/services` and API healthy.

- [ ] **Step 1: Run the deployment contract test**

Run: `pytest tests/test_deployment_config.py -v`

Expected: PASS before publication.

- [ ] **Step 2: Create a release branch and pull request**

```bash
git switch -c codex/company-service-catalog
git push -u origin codex/company-service-catalog
gh pr create --fill
```

- [ ] **Step 3: After merge, publish and redeploy**

Wait for the image pipeline, update the Portainer tag and redeploy. Confirm `Database migrations completed`, `Application startup complete`, and `GET /ready` with `200`.

- [ ] **Step 4: Perform production acceptance checks**

Verify: Services lists each company service once; a professional can be assigned that item with commission; unpaid reservation cannot be manually confirmed; approved payment confirms it; an expired-unpaid-only service can be deleted; a paid service can only be deactivated.

## Plan self-review

- Coverage: Tasks 1–2 cover schema and migration; Task 3 covers management and deletion; Task 4 enforces payment-gated scheduling; Task 5 covers the dashboard; Task 6 covers release and production acceptance.
- Placeholder scan: no deferred or unspecified implementation work remains.
- Interface consistency: all scheduling entry points use `ProfessionalServiceService.is_active_assignment`; commercial fields remain on the catalogue while commission and assignment state remain on `ProfessionalService`.

