from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.payment import Payment
from app.models.product import Product
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

    product = Product(
        name="Shampoo Hidratante",
        description="Shampoo nutritivo profissional",
        category="cabelo",
        price_cents=5000,
        stock_quantity=10,
        weight_kg=Decimal("0.350"),
        active=True,
    )
    db.add(product)
    db.flush()

    product2 = Product(
        name="Condicionador Reconstrutor",
        description="Condicionador para reparação",
        category="cabelo",
        price_cents=3500,
        stock_quantity=15,
        weight_kg=Decimal("0.400"),
        active=True,
    )
    db.add(product2)
    db.flush()

    db.commit()

    return {
        "user": user,
        "product": product,
        "product2": product2,
    }


def seed_appointment(db: Session, entities: dict) -> Appointment:
    apt = Appointment(
        user_id=entities["user"].id,
        professional_id=1,
        service_id=1,
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


def seed_payment(
    db: Session,
    appointment: Appointment | None = None,
    product: Product | None = None,
    user: User | None = None,
) -> Payment:
    now = datetime.now()

    pay = Payment(
        appointment_id=appointment.id if appointment else None,
        user_id=user.id if user else (appointment.user_id if appointment else None),
        product_id=product.id if product else None,
        description=f"Venda {product.name}" if product else "Pagamento teste",
        asaas_payment_id="pay_abc123",
        amount_cents=product.price_cents if product else 5000,
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
