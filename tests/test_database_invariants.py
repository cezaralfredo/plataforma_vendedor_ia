from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.product import Product


def test_appointment_model_declares_constraints():
    names = {constraint.name for constraint in Appointment.__table__.constraints}
    assert "check_appointment_interval" in names
    assert "check_appointment_status" in names


def test_product_model_declares_weight_and_price_constraints():
    names = {constraint.name for constraint in Product.__table__.constraints}
    assert "check_product_price" in names
    assert "check_product_stock" in names
    assert "check_product_weight" in names


def test_product_negative_weight_rejected(db_session: Session):
    product = Product(
        name="Teste Negativo",
        price_cents=1000,
        stock_quantity=5,
        weight_kg=Decimal("-0.500"),
    )
    db_session.add(product)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
