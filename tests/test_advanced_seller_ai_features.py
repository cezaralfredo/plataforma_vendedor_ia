import json
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import Session

from app.models.branch import Branch
from app.models.company_settings import CompanySettings
from app.models.delivery import Delivery
from app.models.product import Product
from app.models.seller import Seller
from app.models.user import User
from app.services.ai.subagents.catalog_subagent import CatalogSubagent
from app.services.ai.subagents.checkout_subagent import CheckoutSubagent
from app.services.ai.subagents.order_status_subagent import OrderStatusSubagent
from app.services.ai.subagents.support_subagent import SupportSubagent
from app.services.recovery_service import SalesRecoveryService


@pytest.fixture
def sample_user(db_session: Session) -> User:
    user = User(
        name="Roberta Lima",
        phone="5585981234567",
        whatsapp_number="5585981234567",
        address="Rua das Palmeiras, 120",
        address_number="120",
        neighborhood="Meireles",
        city="Fortaleza",
        state="CE",
        postal_code="60160-230",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_product(db_session: Session) -> Product:
    prod = Product(
        name="Mesa Lateral Rústica",
        price_cents=29900,
        weight_kg=Decimal("4.500"),
        stock_quantity=10,
        image_url="https://anauedesign.com.br/images/mesa-lateral.jpg",
        active=True,
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)
    return prod


@pytest.fixture
def sample_branch_and_seller(db_session: Session) -> tuple[Branch, Seller]:
    branch = Branch(
        name="Loja Matriz",
        code="MATRIZ",
        city="Fortaleza",
        state="CE",
    )
    db_session.add(branch)
    db_session.commit()
    db_session.refresh(branch)

    seller = Seller(
        name="Luciana Vendedora",
        email="luciana.vendas@loja.com",
        password_hash="hash_abc",
        phone="5585994443322",
        whatsapp_number="5585994443322",
        code="LUC01",
        branch_id=branch.id,
    )
    db_session.add(seller)
    db_session.commit()
    db_session.refresh(seller)
    return branch, seller


@pytest.mark.asyncio
async def test_catalog_subagent_sends_product_photo(db_session: Session, sample_user: User, sample_product: Product):
    mock_gateway = AsyncMock()
    mock_gateway.send_image.return_value = AsyncMock(success=True)

    catalog = CatalogSubagent(db_session, user=sample_user, gateway=mock_gateway)
    res_str = await catalog.execute_tool("enviar_foto_produto", {"produto_id": sample_product.id})
    res = json.loads(res_str)

    assert res["status"] == "sucesso"
    assert res["foto_url"] == sample_product.image_url
    assert res["foto_enviada"] is True
    mock_gateway.send_image.assert_called_once_with(
        sample_user.whatsapp_number,
        sample_product.image_url,
        caption=f"📸 {sample_product.name}\n💰 R$ 299.00",
    )


@pytest.mark.asyncio
async def test_checkout_subagent_creates_delivery_order_pay_on_delivery(
    db_session: Session, sample_user: User, sample_product: Product, sample_branch_and_seller: tuple[Branch, Seller]
):
    branch, seller = sample_branch_and_seller
    sample_user.custom_fields = {"seller_id": seller.id, "branch_id": branch.id}
    db_session.commit()

    checkout = CheckoutSubagent(db_session, user=sample_user)
    args = {
        "produto_id": sample_product.id,
        "quantidade": 2,
        "momento_pagamento": "na_entrega",
        "forma_pagamento": "cartao_credito",
        "endereco_entrega": "Rua das Palmeiras, 120, Apto 302, Meireles, Fortaleza - CE",
        "observacao": "Tocar interfone 302",
    }

    res_str = await checkout.execute_tool("criar_pedido_entrega", args)
    res = json.loads(res_str)

    assert res["status"] == "sucesso"
    assert res["codigo_pedido"].startswith("ENT-")
    assert res["momento_pagamento"] == "na_entrega"
    assert "R$ 598.00" in res["valor_total_formatado"]

    # Verifica persistência no banco de dados
    delivery = db_session.query(Delivery).filter(Delivery.order_code == res["codigo_pedido"]).first()
    assert delivery is not None
    assert delivery.user_id == sample_user.id
    assert delivery.seller_id == seller.id
    assert delivery.payment_timing == "na_entrega"
    assert delivery.payment_status == "pendente"
    assert delivery.delivery_status == "preparando"
    assert delivery.total_amount_cents == 59800


@pytest.mark.asyncio
async def test_order_status_subagent_tracks_real_time_delivery(
    db_session: Session, sample_user: User
):
    # Cria uma entrega em andamento
    delivery = Delivery(
        order_code="ENT-9999",
        user_id=sample_user.id,
        items_description="1x Sofá Retrátil 3 Lugares",
        total_amount_cents=150000,
        payment_method="pix",
        payment_timing="na_entrega",
        payment_status="pendente",
        delivery_status="a_caminho",
        delivery_address=sample_user.full_address,
        delivery_driver_name="Marcos Motoboy",
    )
    db_session.add(delivery)
    db_session.commit()

    subagent = OrderStatusSubagent(db_session, sample_user)
    res_str = await subagent.execute_tool("consultar_status_pedido", {"codigo_pedido": "ENT-9999"})
    res = json.loads(res_str)

    assert res["status"] == "sucesso"
    assert res["total_pedidos"] >= 1
    pedido = res["pedidos"][0]
    assert pedido["codigo"] == "ENT-9999"
    assert pedido["status_entrega"] == "a_caminho"
    assert "A caminho" in pedido["status_entrega_legivel"]
    assert pedido["entregador"] == "Marcos Motoboy"


@pytest.mark.asyncio
async def test_support_subagent_notifies_seller_on_whatsapp(
    db_session: Session, sample_user: User, sample_branch_and_seller: tuple[Branch, Seller]
):
    branch, seller = sample_branch_and_seller
    sample_user.custom_fields = {"seller_id": seller.id, "branch_id": branch.id}
    db_session.commit()

    settings = db_session.query(CompanySettings).first() or CompanySettings()
    mock_gateway = AsyncMock()
    mock_gateway.send_text.return_value = AsyncMock(success=True)

    support = SupportSubagent(settings, db=db_session, user=sample_user, gateway=mock_gateway)
    res_str = await support.execute_tool("acionar_atendente_humano", {"motivo": "Negociar frete grátis"})
    res = json.loads(res_str)

    assert res["status"] == "sucesso"
    assert res["vendedor_notificado"] is True
    assert res["vendedor_nome"] == seller.name

    # Verifica se a mensagem para o vendedor foi despachada
    mock_gateway.send_text.assert_called_once()
    call_args = mock_gateway.send_text.call_args[0]
    assert call_args[0] == seller.whatsapp_number
    assert "Negociar frete grátis" in call_args[1]
    assert sample_user.name in call_args[1]


@pytest.mark.asyncio
async def test_sales_recovery_service_finds_and_contacts_pending_leads(
    db_session: Session, sample_user: User
):
    # Cria entrega pendente
    delivery = Delivery(
        order_code="ENT-8888",
        user_id=sample_user.id,
        items_description="1x Mesa de Jantar 6 Cadeiras",
        total_amount_cents=199900,
        payment_method="pix",
        payment_timing="na_entrega",
        payment_status="pendente",
        delivery_status="preparando",
        delivery_address=sample_user.full_address,
    )
    db_session.add(delivery)
    db_session.commit()

    service = SalesRecoveryService(db_session)
    service.gateway.send_text = AsyncMock(return_value=AsyncMock(success=True))

    result = await service.run_batch_recovery(minutes_idle=0)
    assert result["total_leads_found"] >= 1
    assert result["total_contacted"] >= 1

    # Verifica se marcou last_followup_at
    db_session.refresh(sample_user)
    assert "last_followup_at" in (sample_user.custom_fields or {})


@pytest.mark.asyncio
async def test_checkout_subagent_persists_preferred_bank_and_instructions(
    db_session: Session, sample_user: User, sample_product: Product
):
    checkout = CheckoutSubagent(db_session, sample_user)
    res_str = await checkout.execute_tool(
        "criar_pedido_entrega",
        {
            "produto_id": sample_product.id,
            "quantidade": 1,
            "momento_pagamento": "na_entrega",
            "forma_pagamento": "dinheiro",
            "banco_preferido": "Nubank",
            "instrucoes_entrega": "Deixar na portaria com o porteiro Silva",
        },
    )
    res = json.loads(res_str)
    assert res["status"] == "sucesso"

    db_session.refresh(sample_user)
    assert sample_user.preferred_bank == "Nubank"
    assert sample_user.delivery_instructions == "Deixar na portaria com o porteiro Silva"


@pytest.mark.asyncio
async def test_order_status_subagent_resolves_numeric_id_and_code(
    db_session: Session, sample_user: User
):
    delivery = Delivery(
        order_code="ENT-0042",
        user_id=sample_user.id,
        items_description="1x Luminária Artística",
        total_amount_cents=12000,
        payment_method="pix",
        payment_timing="antecipado",
        payment_status="pago",
        delivery_status="a_caminho",
        delivery_address=sample_user.full_address,
        delivery_driver_name="Marcos Entregador",
    )
    db_session.add(delivery)
    db_session.commit()
    db_session.refresh(delivery)

    subagent = OrderStatusSubagent(db_session, sample_user)

    # 1. Busca por código exato
    res1 = json.loads(await subagent.execute_tool("consultar_status_pedido", {"codigo_pedido": "ENT-0042"}))
    assert res1["status"] == "sucesso"
    assert res1["pedidos"][0]["codigo"] == "ENT-0042"

    # 2. Busca por dígitos (ex: 42)
    res2 = json.loads(await subagent.execute_tool("consultar_status_pedido", {"codigo_pedido": "42"}))
    assert res2["status"] == "sucesso"
    assert res2["pedidos"][0]["codigo"] == "ENT-0042"


@pytest.mark.asyncio
async def test_catalog_subagent_rich_fallback_on_product_without_image(
    db_session: Session, sample_user: User
):
    prod_no_img = Product(
        name="Quadro Abstrato Tons Pastéis",
        price_cents=15000,
        description="Pintura acrílica sobre tela 80x60cm",
        category="Decoração",
        stock_quantity=3,
        image_url=None,
        active=True,
    )
    db_session.add(prod_no_img)
    db_session.commit()

    catalog = CatalogSubagent(db_session, user=sample_user)
    res = json.loads(await catalog.execute_tool("enviar_foto_produto", {"produto_id": prod_no_img.id}))

    assert res["status"] == "sem_foto"
    assert res["produto_nome"] == "Quadro Abstrato Tons Pastéis"
    assert "R$ 150.00" in res["preco_formatado"]
    assert "Pintura acrílica" in res["descricao"]


@pytest.mark.asyncio
async def test_support_subagent_falls_back_to_branch_whatsapp(
    db_session: Session, sample_user: User
):
    branch = Branch(
        name="Filial Aldeota",
        code="ALD01",
        whatsapp_number="5585988112233",
        active=True,
    )
    db_session.add(branch)
    db_session.commit()
    db_session.refresh(branch)

    # Associa o cliente à filial sem vendedor individual
    sample_user.custom_fields = {"branch_id": branch.id}
    db_session.commit()

    mock_gateway = AsyncMock()
    mock_gateway.send_text.return_value = AsyncMock(success=True)

    settings = CompanySettings()
    support = SupportSubagent(settings, db=db_session, user=sample_user, gateway=mock_gateway)
    res = json.loads(await support.execute_tool("acionar_atendente_humano", {"motivo": "Orçamento para empresa"}))

    assert res["status"] == "sucesso"
    assert "Filial Aldeota" in res["vendedor_nome"]
    assert branch.whatsapp_number in res["link_suporte"]

    # Gateway foi chamado com o WhatsApp da filial
    mock_gateway.send_text.assert_called_once()
    assert mock_gateway.send_text.call_args[0][0] == branch.whatsapp_number


@pytest.mark.asyncio
async def test_delivery_and_recovery_uses_dynamic_company_name(
    db_session: Session, sample_user: User
):
    from app.services.delivery_service import DeliveryService

    settings = CompanySettings(company_name="Decor & Arte Brasil")
    db_session.add(settings)
    db_session.commit()

    delivery_service = DeliveryService(db_session)
    assert delivery_service._get_company_name() == "Decor & Arte Brasil"

    recovery_service = SalesRecoveryService(db_session)
    assert recovery_service._get_company_name() == "Decor & Arte Brasil"


@pytest.mark.asyncio
async def test_support_subagent_falls_back_to_configured_company_human_support(
    db_session: Session, sample_user: User
):
    sample_user.custom_fields = {}
    db_session.commit()

    mock_gateway = AsyncMock()
    mock_gateway.send_text.return_value = AsyncMock(success=True)

    settings = CompanySettings(
        company_name="Anauê Móveis",
        human_support_phone="5585977778888",
        human_support_name="Suporte Central",
        human_support_message="Nosso especialista já foi chamado para te atender.",
    )
    support = SupportSubagent(settings, db=db_session, user=sample_user, gateway=mock_gateway)
    res = json.loads(
        await support.execute_tool("acionar_atendente_humano", {"motivo": "Dúvida sobre frete interestadual"})
    )

    assert res["status"] == "sucesso"
    assert res["vendedor_nome"] == "Suporte Central"
    assert "5585977778888" in res["link_suporte"]
    assert res["mensagem_customizada"] == "Nosso especialista já foi chamado para te atender."
    assert "Nosso especialista já foi chamado para te atender" in res["instrucoes"]

    # Gateway notifica o número configurado nas configurações da empresa
    mock_gateway.send_text.assert_called_once()
    assert mock_gateway.send_text.call_args[0][0] == "5585977778888"


@pytest.mark.asyncio
async def test_checkout_subagent_stock_validation_and_decrement(
    db_session: Session, sample_user: User, sample_product: Product
):
    checkout = CheckoutSubagent(db=db_session, user=sample_user)
    initial_stock = sample_product.stock_quantity  # 10

    # 1. Tentativa de compra com quantidade superior ao estoque disponível
    res_fail = json.loads(
        await checkout.execute_tool(
            "criar_pedido_entrega",
            {
                "produto_id": sample_product.id,
                "quantidade": 15,
                "momento_pagamento": "na_entrega",
                "forma_pagamento": "dinheiro",
            },
        )
    )
    assert res_fail["status"] == "estoque_insuficiente"
    assert res_fail["disponivel"] == 10
    assert res_fail["solicitado"] == 15

    # Estoque permanece inalterado
    db_session.refresh(sample_product)
    assert sample_product.stock_quantity == initial_stock

    # 2. Compra com quantidade válida debita o estoque
    res_ok = json.loads(
        await checkout.execute_tool(
            "criar_pedido_entrega",
            {
                "produto_id": sample_product.id,
                "quantidade": 3,
                "momento_pagamento": "na_entrega",
                "forma_pagamento": "pix",
            },
        )
    )
    assert res_ok["status"] == "sucesso"
    db_session.refresh(sample_product)
    assert sample_product.stock_quantity == initial_stock - 3  # 7


@pytest.mark.asyncio
async def test_payment_state_service_updates_delivery_payment_status(
    db_session: Session, sample_user: User, sample_product: Product
):
    from datetime import UTC, datetime

    from app.models.payment import Payment
    from app.services.payment_state_service import apply_payment_state

    payment = Payment(
        user_id=sample_user.id,
        amount_cents=sample_product.price_cents,
        product_id=sample_product.id,
        billing_type="pix",
        status="pending",
    )
    db_session.add(payment)
    db_session.commit()

    delivery = Delivery(
        order_code="ENT-9999",
        user_id=sample_user.id,
        payment_id=payment.id,
        items_description=f"1x {sample_product.name}",
        total_amount_cents=sample_product.price_cents,
        payment_method="pix",
        payment_timing="antecipado",
        payment_status="pendente",
        delivery_status="preparando",
        delivery_address=sample_user.address,
    )
    db_session.add(delivery)
    db_session.commit()

    # Confirmação do pagamento recebido
    apply_payment_state(payment, "received", datetime.now(UTC))
    db_session.commit()
    db_session.refresh(delivery)
    assert delivery.payment_status == "pago"

    # Cancelamento ou expiração do pagamento
    apply_payment_state(payment, "overdue", datetime.now(UTC))
    db_session.commit()
    db_session.refresh(delivery)
    assert delivery.payment_status == "cancelado"


@pytest.mark.asyncio
async def test_order_status_subagent_distinguishes_pending_pix_from_paid(
    db_session: Session, sample_user: User
):
    delivery = Delivery(
        order_code="ENT-1234",
        user_id=sample_user.id,
        items_description="1x Perfume Premium",
        total_amount_cents=15000,
        payment_method="pix",
        payment_timing="antecipado",
        payment_status="pendente",
        delivery_status="preparando",
        delivery_address="Rua Teste, 100",
    )
    db_session.add(delivery)
    db_session.commit()

    order_status = OrderStatusSubagent(db_session, sample_user)

    # 1. Quando pendente, deve informar que aguarda pagamento PIX e NÃO "Pago com sucesso"
    res_pending = json.loads(await order_status.execute_tool("consultar_status_pedido", {}))
    assert res_pending["total_pedidos"] == 1
    pedido = res_pending["pedidos"][0]
    assert "Aguardando pagamento PIX" in pedido["pagamento_info"]
    assert "Pago com sucesso" not in pedido["pagamento_info"]
    assert "pedido_id" in pedido
    assert "codigo" in pedido

    # 2. Quando pago, deve exibir confirmação de pagamento
    delivery.payment_status = "pago"
    db_session.commit()

    res_paid = json.loads(await order_status.execute_tool("consultar_status_pedido", {}))
    pedido_pago = res_paid["pedidos"][0]
    assert "Pago com sucesso ✅" in pedido_pago["pagamento_info"]



