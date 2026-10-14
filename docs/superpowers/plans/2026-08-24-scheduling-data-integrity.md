# Scheduling and Data Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scheduling timezone-safe, lifecycle-consistent, and resistant to concurrent double booking while aligning CRUD behavior and production constraints.

**Architecture:** Normalize all scheduling comparisons through a small business-time module; centralize appointment lifecycle rules in the appointment repository/service; enforce the final concurrency guarantee with a PostgreSQL exclusion constraint. Keep service checks for friendly errors and SQLite compatibility.

**Tech Stack:** Python 3.11 `zoneinfo`, FastAPI, SQLAlchemy 2, PostgreSQL 16, Alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-platform-hardening-design.md`

## Global Constraints

- Business timezone is configurable through `APP_TIMEZONE` and defaults to `America/Sao_Paulo`.
- Naive input remains accepted as local business time.
- Expired unpaid reservations never block availability.
- PostgreSQL, not an in-process lock, is the final concurrency authority.
- Existing conflicting production data aborts migration; it is never deleted automatically.
- Write and observe every regression test fail before changing production behavior.

---

### Task 1: Business-time normalization

**Files:**
- Create: `app/business_time.py`
- Modify: `app/config.py`
- Modify: `app/services/appointment_service.py`
- Modify: `app/services/availability_service.py`
- Modify: `app/schemas/appointment.py`
- Modify: `app/schemas/availability.py`
- Create: `tests/test_business_time.py`

**Interfaces:**
- Produces: `business_tz() -> ZoneInfo`
- Produces: `as_business_time(value: datetime) -> datetime`
- Produces: `business_datetime(day: date, value: time) -> datetime`
- Produces: `utc_now() -> datetime`

- [ ] **Step 1: Write failing timezone tests**

```python
def test_naive_datetime_is_interpreted_in_business_timezone():
    value = as_business_time(datetime(2026, 8, 24, 9, 0))
    assert value.isoformat() == "2026-08-24T09:00:00-03:00"

def test_utc_datetime_is_converted_to_business_timezone():
    value = as_business_time(datetime(2026, 8, 24, 12, 0, tzinfo=UTC))
    assert value.isoformat() == "2026-08-24T09:00:00-03:00"

def test_booking_with_z_suffix_compares_against_local_availability(client, seeded_entities):
    response = client.post("/api/appointments", json={
        "user_id": seeded_entities["user"].id,
        "professional_id": seeded_entities["professional"].id,
        "service_id": seeded_entities["service"].id,
        "start_time": "2026-07-30T12:00:00Z",
        "end_time": "2026-07-30T13:00:00Z",
    })
    assert response.status_code == 201
    assert response.json()["start_time"].endswith("-03:00")
```

- [ ] **Step 2: Run and observe missing helper and naive/aware comparison failure**

Run: `pytest tests/test_business_time.py -v`

- [ ] **Step 3: Implement normalization and same-local-day validation**

```python
def as_business_time(value: datetime) -> datetime:
    timezone = business_tz()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)

def business_datetime(day: date, value: time) -> datetime:
    return datetime.combine(day, value, tzinfo=business_tz())
```

Normalize appointment start/end before duration and availability checks. Normalize appointment values read from SQLite before Python comparison. Build availability periods with `business_datetime`. Appointment response validation attaches/converts the offset so SQLite tests and production responses share the contract.

- [ ] **Step 4: Run focused scheduling tests**

Run: `pytest tests/test_business_time.py tests/test_flow_completo.py -v`

- [ ] **Step 5: Commit**

```text
git add app/business_time.py app/config.py app/services/appointment_service.py app/services/availability_service.py app/schemas tests/test_business_time.py
git commit -m "fix: normalize scheduling in business timezone"
```

### Task 2: Expiration and appointment state machine

**Files:**
- Modify: `app/repositories/appointment_repo.py`
- Modify: `app/services/appointment_service.py`
- Modify: `app/services/availability_service.py`
- Modify: `app/services/payment_service.py`
- Create: `tests/test_appointment_lifecycle.py`

**Interfaces:**
- Produces: `AppointmentRepository.expire_reservations(now: datetime) -> int`.
- Produces: `AppointmentRepository.find_conflicting(..., now: datetime) -> list[Appointment]` with expiry-aware filtering.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_awaiting_payment_expires_and_releases_slot(client, db_session, seeded_entities):
    appointment = seed_expired_awaiting_payment(db_session, seeded_entities)
    response = client.get(
        f"/api/availability/slots/{appointment.professional_id}/{appointment.service_id}",
        params={"date": appointment.start_time.date().isoformat()},
    )
    assert any(slot["start"].startswith(appointment.start_time.strftime("%Y-%m-%dT%H:%M")) for slot in response.json())
    db_session.refresh(appointment)
    assert appointment.status == "cancelled"

def test_completed_appointment_cannot_be_cancelled(client, completed_appointment):
    response = client.post(f"/api/appointments/{completed_appointment.id}/cancel")
    assert response.status_code == 409

def test_confirm_is_idempotent(client, confirmed_appointment):
    response = client.post(f"/api/appointments/{confirmed_appointment.id}/confirm")
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
```

- [ ] **Step 2: Run and observe stale awaiting-payment and invalid terminal transitions**

Run: `pytest tests/test_appointment_lifecycle.py -v`

- [ ] **Step 3: Implement expiry-aware repository queries and service transitions**

```python
ACTIVE_WHILE_UNEXPIRED = ("pending", "awaiting_payment")
ALWAYS_BLOCKING = ("confirmed", "completed")

def expire_reservations(self, now: datetime) -> int:
    return self.db.query(Appointment).filter(
        Appointment.status.in_(ACTIVE_WHILE_UNEXPIRED),
        Appointment.expires_at.is_not(None),
        Appointment.expires_at <= now,
    ).update({"status": "cancelled"}, synchronize_session=False)
```

Availability calls expiration before calculating periods. `find_conflicting` uses the active/expiry predicate. Charge creation expires first and rejects a cancelled/expired appointment. Implement idempotent cancel/confirm behavior exactly as specified.

- [ ] **Step 4: Run lifecycle, payment, and availability tests**

Run: `pytest tests/test_appointment_lifecycle.py tests/test_business_time.py tests/test_flow_completo.py -v`

- [ ] **Step 5: Commit**

```text
git add app/repositories/appointment_repo.py app/services tests/test_appointment_lifecycle.py
git commit -m "fix: expire unpaid reservations consistently"
```

### Task 3: PostgreSQL constraints and concurrent booking

**Files:**
- Modify: `app/models/appointment.py`
- Modify: `app/models/availability.py`
- Modify: `app/models/service.py`
- Modify: `app/models/payment.py`
- Modify: `app/services/appointment_service.py`
- Create: `alembic/versions/4a6f9d2e1b3c_enforce_scheduling_invariants.py`
- Create: `tests/test_database_invariants.py`

**Interfaces:**
- Produces database constraint: `exclude_professional_overlapping_appointments`.
- Produces check constraints matching ORM names and migration names.

- [ ] **Step 1: Write failing invariant and conflict-translation tests**

```python
def test_overlapping_insert_is_rejected_by_postgres(postgres_session, seeded_entities):
    first = appointment_for(seeded_entities, "2026-08-26T09:00:00-03:00")
    second = appointment_for(seeded_entities, "2026-08-26T09:30:00-03:00")
    postgres_session.add(first)
    postgres_session.commit()
    postgres_session.add(second)
    with pytest.raises(IntegrityError):
        postgres_session.commit()

def test_exclusion_conflict_becomes_http_409(client, monkeypatch, seeded_entities):
    monkeypatch.setattr(AppointmentRepository, "create", raise_exclusion_integrity_error)
    response = create_valid_appointment(client, seeded_entities)
    assert response.status_code == 409
```

Mark the PostgreSQL-only test with `pytest.mark.postgres` and skip it when the active test URL is SQLite.

- [ ] **Step 2: Verify the PostgreSQL test permits overlap and translation test errors**

Run: `pytest tests/test_database_invariants.py -v`

- [ ] **Step 3: Add the migration preflight and constraints**

The migration first executes an overlap query joining active appointments for the same professional and raises a PostgreSQL exception when a pair exists. Then:

```python
op.execute('CREATE EXTENSION IF NOT EXISTS btree_gist')
op.create_exclude_constraint(
    "exclude_professional_overlapping_appointments",
    "appointments",
    ("professional_id", "="),
    (sa.text("tstzrange(start_time, end_time, '[)')"), "&&"),
    where=sa.text("status IN ('pending', 'awaiting_payment', 'confirmed', 'completed')"),
    using="gist",
)
```

Add named checks for appointment interval/status, availability type/day/times, service duration/price, and payment amount/type/status. Add matching ORM constraints; guard PostgreSQL `ExcludeConstraint` with `.ddl_if(dialect="postgresql")` so SQLite metadata creation remains valid.

Catch only the named exclusion constraint in appointment creation, rollback, and raise `ValueError("Já existe uma reserva neste horário")`. Re-raise unrelated integrity errors.

- [ ] **Step 4: Run migration and invariant verification**

Run with PostgreSQL test URL: `alembic upgrade head`

Run: `pytest tests/test_database_invariants.py tests/test_flow_completo.py -v`

Run: `alembic check`

- [ ] **Step 5: Commit**

```text
git add app/models app/services/appointment_service.py alembic/versions tests/test_database_invariants.py
git commit -m "fix: prevent concurrent double booking"
```

### Task 4: Correct partial updates and relationship validation

**Files:**
- Modify: `app/repositories/base.py`
- Modify: `app/services/user_service.py`
- Modify: `app/services/professional_service.py`
- Modify: `app/services/service_service.py`
- Modify: `app/services/availability_service.py`
- Modify: `app/api/users.py`
- Modify: `app/api/professionals.py`
- Modify: `app/api/services.py`
- Modify: `app/api/availability.py`
- Create: `tests/test_crud_integrity.py`

**Interfaces:**
- Changes: `BaseRepository.update` applies every provided key, including `None`.
- Produces: service update methods that pass only `model_dump(exclude_unset=True)`.

- [ ] **Step 1: Write failing nullable, duplicate, and foreign-key tests**

```python
def test_user_can_clear_optional_email(client, seeded_entities):
    response = client.put(f"/api/users/{seeded_entities['user'].id}", json={"email": None})
    assert response.status_code == 200
    assert response.json()["email"] is None

def test_duplicate_phone_update_returns_409(client, two_users):
    response = client.put(f"/api/users/{two_users[1].id}", json={"phone": two_users[0].phone})
    assert response.status_code == 409

def test_service_rejects_unknown_professional(client):
    response = client.post("/api/services", json={
        "professional_id": 999999, "name": "Corte", "duration_minutes": 30, "price_cents": 1000,
    })
    assert response.status_code == 409

def test_availability_update_validates_merged_interval(client, seeded_entities):
    availability = seeded_entities["availability"]
    response = client.put(f"/api/availability/{availability.id}", json={"end_time": "07:00:00"})
    assert response.status_code == 422
```

- [ ] **Step 2: Run and observe fields cannot clear and integrity errors escape**

Run: `pytest tests/test_crud_integrity.py -v`

- [ ] **Step 3: Implement explicit-None updates and service validation**

```python
def update(self, id: int, **kwargs):
    obj = self.get(id)
    if not obj:
        return None
    for key, value in kwargs.items():
        setattr(obj, key, value)
    self.db.commit()
    self.db.refresh(obj)
    return obj
```

All update services use `exclude_unset=True`. User routes use `UserService`. Availability merges stored values with supplied values and validates through `AvailabilityCreate` before update. Service/availability creation checks `Professional`. Catch known unique and foreign-key failures, rollback, and map them to domain `ValueError`; API maps domain conflicts to `409` and invalid merged schedules to `422`.

- [ ] **Step 4: Run CRUD and full API tests**

Run: `pytest tests/test_crud_integrity.py tests/test_flow_completo.py tests/test_mcp_clientes.py -v`

- [ ] **Step 5: Commit**

```text
git add app/repositories/base.py app/services app/api tests/test_crud_integrity.py
git commit -m "fix: preserve CRUD data invariants"
```

### Task 5: Safe deletion conflicts

**Files:**
- Modify: `app/repositories/base.py`
- Modify: `app/services/user_service.py`
- Modify: `app/services/professional_service.py`
- Modify: `app/services/service_service.py`
- Modify: `app/api/users.py`
- Modify: `app/api/professionals.py`
- Modify: `app/api/services.py`
- Modify: `tests/test_crud_integrity.py`

**Interfaces:**
- Produces: `RelatedRecordsError(resource: str)` translated to HTTP `409`.

- [ ] **Step 1: Add failing delete-conflict tests**

```python
def test_professional_with_history_cannot_be_deleted(client, seeded_entities):
    response = client.delete(f"/api/professionals/{seeded_entities['professional'].id}")
    assert response.status_code == 409
    assert "desative" in response.json()["detail"].lower()

def test_user_with_appointment_cannot_be_deleted(client, seeded_appointment):
    response = client.delete(f"/api/users/{seeded_appointment.user_id}")
    assert response.status_code == 409
```

- [ ] **Step 2: Verify current endpoints raise internal database errors**

Run: `pytest tests/test_crud_integrity.py -k cannot_be_deleted -v`

- [ ] **Step 3: Roll back failed deletes and return domain conflicts**

Catch `IntegrityError` inside repository delete, roll back, and raise `RelatedRecordsError`. Services supply resource-specific guidance. Do not cascade-delete historical appointments or payments.

- [ ] **Step 4: Run CRUD suite**

Run: `pytest tests/test_crud_integrity.py -v`

- [ ] **Step 5: Commit**

```text
git add app/repositories/base.py app/services app/api tests/test_crud_integrity.py
git commit -m "fix: report safe deletion conflicts"
```

### Task 6: Admin query and KPI correctness

**Files:**
- Modify: `app/admin/service.py`
- Modify: `app/admin/router.py`
- Create: `tests/test_admin_queries.py`

**Interfaces:**
- Produces: latest-payment correlated subquery used by appointment list/detail.
- Changes: admin `page >= 1` and `1 <= page_size <= 100`.

- [ ] **Step 1: Write failing duplicate and KPI tests**

```python
def test_appointment_list_returns_one_row_with_latest_payment(db_session, seeded_appointment):
    old, latest = add_two_payments(db_session, seeded_appointment)
    rows, total = AdminService(db_session).list_appointments()
    assert total == 1
    assert len(rows) == 1
    assert rows[0]["payment_id"] == latest.id

def test_confirmed_payment_is_not_counted_pending(db_session, confirmed_payment):
    assert AdminService(db_session).get_kpis()["payments_pending"] == 0

def test_admin_rejects_zero_page(admin_client):
    assert admin_client.get("/admin/api/appointments?page=0").status_code == 422
```

- [ ] **Step 2: Run and observe duplicate rows, wrong KPI, and unbounded pagination**

Run: `pytest tests/test_admin_queries.py -v`

- [ ] **Step 3: Join only the deterministic latest payment and bound pagination**

```python
latest_payment_id = (
    select(func.max(Payment.id))
    .where(Payment.appointment_id == Appointment.id)
    .correlate(Appointment)
    .scalar_subquery()
)
query = query.outerjoin(Payment, Payment.id == latest_payment_id)
```

Count pending payments with `Payment.status == "pending"`. Declare FastAPI `Query(ge=1)` for page and `Query(ge=1, le=100)` for page size.

- [ ] **Step 4: Run admin and complete Package 2 tests**

Run: `pytest tests/test_business_time.py tests/test_appointment_lifecycle.py tests/test_database_invariants.py tests/test_crud_integrity.py tests/test_admin_queries.py tests/test_flow_completo.py -v`

Run: `ruff check app tests`

- [ ] **Step 5: Commit**

```text
git add app/admin tests/test_admin_queries.py
git commit -m "fix: correct admin operational data"
```
