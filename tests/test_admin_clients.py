from datetime import datetime

from app.admin.service import AdminService
from app.config import settings
from app.models.user import User
from tests.seed import seed_appointment, seed_data, seed_payment


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def test_client_without_history_is_deleted(db_session):
    client = User(name="Cliente avulso", phone="11911112222")
    db_session.add(client)
    db_session.commit()
    client_id = client.id

    outcome = AdminService(db_session).archive_or_delete_user(client_id)

    assert outcome == "deleted"
    assert db_session.get(User, client_id) is None


def test_client_with_appointment_history_is_archived_and_can_be_reactivated(db_session):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    client = appointment.user

    outcome = AdminService(db_session).archive_or_delete_user(client.id)

    assert outcome == "archived"
    db_session.refresh(client)
    assert client.active is False

    reactivated = AdminService(db_session).reactivate_user(client.id)

    assert reactivated is not None
    assert reactivated.active is True


def test_admin_client_api_returns_paginated_history_summary(anonymous_client, db_session):
    appointment = seed_appointment(db_session, seed_data(db_session))
    payment = seed_payment(db_session, appointment)
    payment.status = "received"
    db_session.commit()

    response = anonymous_client.get(
        "/admin/api/clients?page=1&page_size=20&status=active",
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["total_pages"] == 1
    assert payload["data"][0]["appointments_total"] == 1
    assert payload["data"][0]["payments_received_total"] == 1
    assert datetime.fromisoformat(payload["data"][0]["last_appointment_at"]) == appointment.start_time
    assert "cpf_cnpj" not in payload["data"][0]
    assert "asaas_customer_id" not in payload["data"][0]


def test_admin_client_api_manages_client_lifecycle(anonymous_client, db_session):
    created = anonymous_client.post(
        "/admin/api/clients",
        headers=_admin_headers(),
        json={"name": "Maria", "phone": "11955556666", "email": "maria@example.com"},
    )

    assert created.status_code == 201
    client_id = created.json()["id"]
    updated = anonymous_client.put(
        f"/admin/api/clients/{client_id}",
        headers=_admin_headers(),
        json={"name": "Maria Silva"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Maria Silva"

    deleted = anonymous_client.delete(
        f"/admin/api/clients/{client_id}", headers=_admin_headers()
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"outcome": "deleted"}
    assert db_session.get(User, client_id) is None


def test_admin_client_api_reports_unique_contact_conflict(anonymous_client, db_session):
    db_session.add(User(name="Existente", phone="11911110000", email="same@example.com"))
    db_session.commit()

    response = anonymous_client.post(
        "/admin/api/clients",
        headers=_admin_headers(),
        json={"name": "Duplicado", "phone": "11911110000", "email": "same@example.com"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Telefone ou e-mail já cadastrado."}


def test_admin_clients_page_is_in_navigation_and_hides_sensitive_identifiers(
    anonymous_client,
):
    response = anonymous_client.get("/admin/clients", headers=_admin_headers())

    assert response.status_code == 200
    assert 'href="/admin/clients"' in response.text
    assert "Gestão de Clientes" in response.text
    assert "CPF/CNPJ" not in response.text
    assert "ID Asaas" not in response.text
    assert "admin-mobile-list md:hidden" in response.text
    assert "admin-table hidden md:block" in response.text
    assert "Importar clientes" in response.text
    assert "openImport()" in response.text
    assert "importModalOpen" in response.text


def test_admin_client_api_import_csv(anonymous_client, db_session):
    csv_bytes = b"Nome,Telefone,Email,Cidade,Tags\nAdmin Importado,85994445555,admin.imp@teste.com,Fortaleza,vip\n"
    response = anonymous_client.post(
        "/admin/api/clients/import/csv?source=admin_panel",
        headers=_admin_headers(),
        files={"file": ("clientes.csv", csv_bytes, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["created"] == 1
    assert payload["errors"] == 0
    assert db_session.query(User).filter(User.phone == "5585994445555").first() is not None


def test_admin_client_api_standardized_fields_and_validation(anonymous_client, db_session):
    # Name is mandatory
    resp_empty_name = anonymous_client.post(
        "/admin/api/clients",
        headers=_admin_headers(),
        json={"name": "   ", "phone": "11988887777"},
    )
    assert resp_empty_name.status_code == 422

    # Phone is mandatory
    resp_empty_phone = anonymous_client.post(
        "/admin/api/clients",
        headers=_admin_headers(),
        json={"name": "Carlos", "phone": ""},
    )
    assert resp_empty_phone.status_code == 422

    # Creation with standardized fields (matching CSV model)
    created = anonymous_client.post(
        "/admin/api/clients",
        headers=_admin_headers(),
        json={
            "name": "Carlos Silva",
            "phone": "11988887777",
            "email": "carlos@teste.com",
            "city": "São Paulo",
            "state": "sp",
            "tags": ["vip", "recorrente"],
            "notes": "Cliente preferencial",
        },
    )
    assert created.status_code == 201
    data = created.json()
    assert data["name"] == "Carlos Silva"
    assert data["phone"] == "11988887777"
    assert data["city"] == "São Paulo"
    assert data["state"] == "SP"
    assert data["tags"] == ["vip", "recorrente"]
    assert data["notes"] == "Cliente preferencial"

    client_id = data["id"]

    # Update with tags as comma-separated string and changed notes
    updated = anonymous_client.put(
        f"/admin/api/clients/{client_id}",
        headers=_admin_headers(),
        json={
            "city": "Campinas",
            "state": "SP",
            "tags": "vip, fidelidade",
            "notes": "Atendido com sucesso",
        },
    )
    assert updated.status_code == 200
    up_data = updated.json()
    assert up_data["city"] == "Campinas"
    assert up_data["tags"] == ["vip", "fidelidade"]
    assert up_data["notes"] == "Atendido com sucesso"

    # Search by city works
    list_resp = anonymous_client.get(
        "/admin/api/clients?search=Campinas",
        headers=_admin_headers(),
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1
    found = next(c for c in list_resp.json()["data"] if c["id"] == client_id)
    assert found["city"] == "Campinas"
    assert found["tags"] == ["vip", "fidelidade"]


