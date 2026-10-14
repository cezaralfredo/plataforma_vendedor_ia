from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from tests.seed import seed_appointment, seed_data


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


def test_company_service_creation_does_not_depend_on_professional(client: TestClient):
    response = client.post(
        "/api/services",
        json={
            "professional_id": 999999,
            "name": "Corte",
            "duration_minutes": 30,
            "price_cents": 1000,
        },
    )
    assert response.status_code == 201
    assert "professional_id" not in response.json()


def test_availability_update_validates_merged_interval(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    availability = entities["availability"]
    response = client.put(
        f"/api/availability/{availability.id}",
        json={"end_time": "07:00:00"},
    )
    assert response.status_code == 422


def test_professional_with_history_cannot_be_deleted(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    seed_appointment(db_session, entities)
    response = client.delete(f"/api/professionals/{entities['professional'].id}")
    assert response.status_code == 409
    assert "desative" in response.json()["detail"].lower()


def test_user_with_appointment_cannot_be_deleted(
    client: TestClient,
    db_session: Session,
):
    entities = seed_data(db_session)
    appointment = seed_appointment(db_session, entities)
    response = client.delete(f"/api/users/{appointment.user_id}")
    assert response.status_code == 409
