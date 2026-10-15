from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from tests.seed import seed_appointment, seed_data


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key}


def test_user_can_clear_optional_email(client: TestClient, db_session: Session):
    entities = seed_data(db_session)
    response = client.put(
        f"/api/users/{entities['user'].id}",
        json={"email": None},
    )
    assert response.status_code == 200
    assert response.json()["email"] is None


def test_duplicate_phone_update_returns_409(client: TestClient, db_session: Session):
    entities = seed_data(db_session)
    second = User(name="Outro", phone="+5511777777777")
    db_session.add(second)
    db_session.commit()
    response = client.put(
        f"/api/users/{second.id}",
        json={"phone": entities["user"].phone},
    )
    assert response.status_code == 409


def test_product_crud_and_weight(client: TestClient, db_session: Session):
    # Criar produto com peso
    response = client.post(
        "/admin/api/products",
        json={
            "name": "Condicionador Teste",
            "price_cents": 3200,
            "weight_kg": 0.450,
            "stock_quantity": 8,
        },
        headers=_admin_headers(),
    )
    assert response.status_code == 200
    data = response.json()
    product_id = data["id"]
    assert float(data["weight_kg"]) == 0.450

    # Atualizar peso do produto
    update_resp = client.put(
        f"/admin/api/products/{product_id}",
        json={"weight_kg": 0.500},
        headers=_admin_headers(),
    )
    assert update_resp.status_code == 200
    assert float(update_resp.json()["weight_kg"]) == 0.500


def test_user_with_appointment_cannot_be_deleted(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    response = client.delete(f"/api/users/{appointment.user_id}")
    assert response.status_code == 409
