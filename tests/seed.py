from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.availability import Availability
from app.models.payment import Payment
from app.models.professional import Professional
from app.models.professional_service import ProfessionalService
from app.models.service import Service
from app.models.user import User


def seed_data(db: Session) -> dict:
    user = User(
        name="João Silva",
        phone="+5511999999999",
        email="joao@email.com",
        created_at=datetime(2026, 7, 29, 10, 0, 0),
    )
    db.add(user)
    db.flush()

    professional = Professional(
        name="Maria Souza",
        phone="+5511988888888",
        email="maria@email.com",
        bio="Cabeleireira profissional",
        active=True,
    )
    db.add(professional)
    db.flush()

    service = Service(
        name="Corte de cabelo",
        description="Corte masculino e feminino",
        duration_minutes=60,
        price_cents=5000,
        category="corte",
    )
    db.add(service)
    db.flush()

    service2 = Service(
        name="Escova",
        description="Escova modeladora",
        duration_minutes=45,
        price_cents=3500,
        category="escova",
    )
    db.add(service2)
    db.flush()

    db.add_all(
        [
            ProfessionalService(
                professional_id=professional.id,
                service_id=service.id,
            ),
            ProfessionalService(
                professional_id=professional.id,
                service_id=service2.id,
            ),
        ]
    )

    availability = Availability(
        professional_id=professional.id,
        day_of_week=2,
        start_time=time(8, 0),
        end_time=time(12, 0),
    )
    db.add(availability)

    availability2 = Availability(
        professional_id=professional.id,
        day_of_week=2,
        start_time=time(13, 0),
        end_time=time(18, 0),
    )
    db.add(availability2)

    availability3 = Availability(
        professional_id=professional.id,
        specific_date=date(2026, 7, 30),
        start_time=time(9, 0),
        end_time=time(17, 0),
    )
    db.add(availability3)

    db.commit()

    return {
        "user": user,
        "professional": professional,
        "service": service,
        "service2": service2,
        "availability": availability,
    }


def seed_appointment(db: Session, entities: dict) -> Appointment:
    apt = Appointment(
        user_id=entities["user"].id,
        professional_id=entities["professional"].id,
        service_id=entities["service"].id,
        start_time=datetime(2026, 7, 30, 9, 0, 0),
        end_time=datetime(2026, 7, 30, 10, 0, 0),
        status="awaiting_payment",
        created_at=datetime(2026, 7, 29, 10, 0, 0),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db.add(apt)
    db.commit()
    db.flush()
    return apt


def seed_payment(db: Session, appointment: Appointment) -> Payment:
    now = datetime.now()

    pay = Payment(
        appointment_id=appointment.id,
        asaas_payment_id="pay_abc123",
        amount_cents=5000,
        billing_type="pix",
        status="pending",
        invoice_url="https://asaas.com/pay/abc123",
        created_at=now,
        updated_at=now,
    )
    db.add(pay)
    db.commit()
    db.flush()
    return pay
