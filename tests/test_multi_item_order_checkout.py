import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.delivery import Delivery
from app.models.product import Product
from app.models.user import User
from app.services.ai.subagents.checkout_subagent import CheckoutSubagent


@pytest.mark.asyncio
async def test_checkout_multi_item_order_with_fractional_weight_and_address(db_session: Session):
    """
    Testa criação de pedido com múltiplos produtos (ex: Cará 1.5kg + Camarão Filé 1kg),
    totalizando R$ 84,50, captura do endereço informado e status de pagamento pendente.
    """
    user = User(name="Cezar Alfredo", phone="5585996277707")
    prod_cara = Product(
        name="Cará",
        category="Tilápia",
        price_cents=1300,  # R$ 13,00 / kg
        weight_kg=1.0,
        stock_quantity=100,
        active=True,
    )
    prod_camarao = Product(
        name="Camarão",
        category="Filé",
        price_cents=6500,  # R$ 65,00 / kg
        weight_kg=1.0,
        stock_quantity=100,
        active=True,
    )
    db_session.add_all([user, prod_cara, prod_camarao])
    db_session.commit()

    checkout = CheckoutSubagent(db=db_session, user=user)

    args = {
        "itens": [
            {"produto_id": prod_cara.id, "quantidade": 1.5},
            {"produto_id": prod_camarao.id, "quantidade": 1.0},
        ],
        "nome_cliente": "Cezar Alfredo",
        "endereco_entrega": "Rua Firmo Ananias Cardoso, 622, Sapiranga",
        "momento_pagamento": "antecipado",
        "forma_pagamento": "pix",
    }

    res_str = await checkout.execute_tool("criar_pedido_entrega", args)
    data = json.loads(res_str)

    assert data["status"] == "sucesso"
    assert data["valor_total_formatado"] == "R$ 84.50"
    assert data["valor_total_cents"] == 8450
    assert data["endereco_entrega"] == "Rua Firmo Ananias Cardoso, 622, Sapiranga"
    assert len(data["itens"]) == 2

    # Verifica persistência no banco de dados
    db_session.refresh(user)
    assert user.address == "Rua Firmo Ananias Cardoso, 622, Sapiranga"
    assert user.name == "Cezar Alfredo"

    delivery = db_session.query(Delivery).filter(Delivery.order_code == data["codigo_pedido"]).first()
    assert delivery is not None
    assert delivery.user_id == user.id
    assert delivery.total_amount_cents == 8450
    assert delivery.payment_timing == "antecipado"
    assert delivery.payment_status == "pendente"  # Nunca 'pago' antes de pagar!
    assert delivery.delivery_address == "Rua Firmo Ananias Cardoso, 622, Sapiranga"
    assert "Cará" in delivery.items_description
    assert "Camarão" in delivery.items_description

    # Verifica débito no estoque
    db_session.refresh(prod_cara)
    db_session.refresh(prod_camarao)
    assert prod_cara.stock_quantity == 98  # round(1.5) = 2
    assert prod_camarao.stock_quantity == 99  # 1


@pytest.mark.asyncio
async def test_checkout_pix_charge_with_multi_items_and_address(db_session: Session):
    """
    Testa tool 'criar_pedido_cobranca' com múltiplos itens e endereço completo.
    """
    user = User(name="Cliente", phone="5585988887777")
    p1 = Product(name="Item A", price_cents=2000, stock_quantity=10, active=True)
    p2 = Product(name="Item B", price_cents=3000, stock_quantity=10, active=True)
    db_session.add_all([user, p1, p2])
    db_session.commit()

    checkout = CheckoutSubagent(db=db_session, user=user)

    args = {
        "itens": [
            {"produto_id": p1.id, "quantidade": 2},
            {"produto_id": p2.id, "quantidade": 1},
        ],
        "nome_cliente": "Maria Silva",
        "endereco_entrega": "Av Beira Mar, 1000",
    }

    with patch.object(checkout.payment_service.asaas, "create_payment", new_callable=AsyncMock) as mock_asaas, \
         patch.object(checkout.payment_service.asaas, "list_customers", new_callable=AsyncMock) as mock_cust:
        mock_cust.return_value = [{"id": "cus_999", "mobilePhone": user.phone}]
        mock_asaas.return_value = {
            "id": "pay_999",
            "status": "PENDING",
            "invoiceUrl": "https://sandbox.asaas.com/i/test999",
            "value": 70.00,
        }

        res_str = await checkout.execute_tool("criar_pedido_cobranca", args)
        data = json.loads(res_str)

    assert data["status"] == "sucesso"
    assert data["valor_total_formatado"] == "R$ 70.00"
    assert data["valor_total_cents"] == 7000
    assert data["endereco_entrega"] == "Av Beira Mar, 1000"
    assert data["link_pagamento"] == "https://sandbox.asaas.com/i/test999"

    db_session.refresh(user)
    assert user.name == "Maria Silva"
    assert user.address == "Av Beira Mar, 1000"

    delivery = db_session.query(Delivery).filter(Delivery.order_code == data["codigo_pedido"]).first()
    assert delivery is not None
    assert delivery.delivery_address == "Av Beira Mar, 1000"
    assert delivery.payment_status == "pendente"
