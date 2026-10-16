from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.company_settings import CompanySettings
from app.models.product import Product
from app.models.user import User
from app.services.seller_ai_service import SellerAIService
from app.services.whatsapp.base import InboundMessage


@pytest.mark.asyncio
async def test_seller_ai_answers_catalog_with_weight(db_session: Session):
    settings = db_session.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(company_name="Loja Teste")
        db_session.add(settings)
    settings.company_name = "Loja Teste"

    prod = Product(
        name="Shampoo Hidratante 500ml",
        price_cents=4500,
        weight_kg=Decimal("0.550"),
        stock_quantity=20,
        active=True,
    )
    db_session.add(prod)
    db_session.commit()

    service = SellerAIService(db_session)
    inbound = InboundMessage(
        provider="waha",
        sender_phone="5585991112222",
        sender_name="Lucas",
        text="Olá, gostaria de ver os produtos e preços",
        message_id="msg-1",
    )

    with patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = AsyncMock()
        response = await service.handle_inbound_message(inbound)

        assert "Shampoo Hidratante 500ml" in response
        assert "R$ 45.00" in response
        assert "0.550 kg" in response
        mock_send.assert_called_once()

    # Verifica se a conversa foi salva na tabela chat_messages
    messages = db_session.query(ChatMessage).filter(ChatMessage.phone == "5585991112222").all()
    assert len(messages) >= 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_seller_ai_creates_direct_purchase_charge(db_session: Session):
    prod = Product(
        name="Kit Tratamento Capilar",
        price_cents=12000,
        weight_kg=Decimal("1.200"),
        stock_quantity=10,
        active=True,
    )
    db_session.add(prod)
    db_session.commit()

    service = SellerAIService(db_session)
    inbound = InboundMessage(
        provider="evolution",
        sender_phone="5585993334444",
        sender_name="Beatriz",
        text=f"Quero comprar o produto #{prod.id}",
        message_id="msg-2",
    )

    with patch.object(service.payment_service.asaas, "create_payment", new_callable=AsyncMock) as mock_asaas, \
         patch.object(service.payment_service.asaas, "list_customers", new_callable=AsyncMock) as mock_cust, \
         patch.object(service.payment_service.asaas, "create_customer", new_callable=AsyncMock) as mock_create_cust, \
         patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send:

        mock_cust.return_value = []
        mock_create_cust.return_value = {"id": "cus_12345"}
        mock_asaas.return_value = {
            "id": "pay_9999",
            "status": "PENDING",
            "invoiceUrl": "https://sandbox.asaas.com/i/pedido123",
            "value": 120.00,
        }

        response = await service.handle_inbound_message(inbound)

        assert "Pedido #" in response
        assert "Kit Tratamento Capilar" in response
        assert "1.200 kg" in response
        assert "https://sandbox.asaas.com/i/pedido123" in response
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_seller_ai_transfers_to_human_support(db_session: Session):
    service = SellerAIService(db_session)
    inbound = InboundMessage(
        provider="meta",
        sender_phone="5585995556666",
        sender_name="Carlos",
        text="Gostaria de falar com um atendente humano",
        message_id="msg-3",
    )

    with patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send:
        response = await service.handle_inbound_message(inbound)

        assert "atendente" in response.lower()
        assert "wa.me" in response
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_seller_ai_seller_attribution_and_commission_from_link(db_session: Session):
    from app.models.branch import Branch
    from app.models.payment import Payment
    from app.models.seller import Seller
    from app.services.company_settings_service import CompanySettingsService

    company_settings = CompanySettingsService(db_session).get_or_create_default()
    company_settings.default_gateway = "pix_direto"
    company_settings.gateway_credentials = {
        "pix_key": "12345678000199",
        "merchant_name": "Minha Empresa",
        "merchant_city": "Sao Paulo",
    }
    db_session.commit()

    branch = Branch(name="Filial Salvador", code="SSA-01", city="Salvador", state="BA")
    db_session.add(branch)
    db_session.commit()

    seller = Seller(
        branch_id=branch.id,
        name="Lucas Vendedor",
        email="lucas@salvador.com",
        password_hash="hash123",
        whatsapp_number="5571999990001",
        code="VEND-SSA-01",
        commission_rate=15.0,  # 15% de comissão
        active=True,
    )
    db_session.add(seller)

    prod = Product(
        name="Perfume Floral 100ml",
        price_cents=20000,
        stock_quantity=10,
        active=True,
    )
    db_session.add(prod)
    db_session.commit()

    service = SellerAIService(db_session)

    # Cliente envia mensagem originada do link do vendedor
    inbound = InboundMessage(
        provider="evolution",
        sender_phone="5571988887777",
        sender_name="Juliana",
        text=f"Olá, fui atendido pelo vendedor VEND-SSA-01 e quero comprar o produto #{prod.id}",
        message_id="msg-seller-1",
    )

    with patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send:
        response = await service.handle_inbound_message(inbound)
        assert "Pedido #" in response
        mock_send.assert_called_once()

    # Verifica se o cliente recebeu os dados do vendedor no custom_fields
    user = service.user_service.find_by_phone("5571988887777")
    assert user is not None
    assert user.custom_fields.get("seller_id") == seller.id
    assert user.custom_fields.get("branch_id") == branch.id
    assert user.custom_fields.get("seller_name") == "Lucas Vendedor"

    # Verifica se o pagamento foi criado atribuído ao vendedor com 15% de comissão
    payment = db_session.query(Payment).filter(Payment.user_id == user.id).first()
    assert payment is not None
    assert payment.seller_id == seller.id
    assert payment.branch_id == branch.id
    # 15% de 20000 = 3000 centavos (R$ 30,00)
    assert payment.commission_amount_cents == 3000


@pytest.mark.asyncio
async def test_seller_ai_human_handoff_pause_and_unpause(db_session: Session):
    service = SellerAIService(db_session)
    phone = "5585997778888"

    # 1. Cliente pede humano
    inbound_human = InboundMessage(
        provider="waha",
        sender_phone=phone,
        sender_name="Danilo",
        text="Quero falar com um atendente humano agora",
        message_id="msg-h-1",
    )
    with patch.object(service.gateway, "send_text", new_callable=AsyncMock):
        resp1 = await service.handle_inbound_message(inbound_human)
        assert "atendente" in resp1.lower()

    # 2. Cliente manda nova mensagem enquanto a IA está pausada -> IA fica em silêncio
    inbound_during_pause = InboundMessage(
        provider="waha",
        sender_phone=phone,
        sender_name="Danilo",
        text="Ainda estou aguardando o atendente...",
        message_id="msg-h-2",
    )
    with patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send_silent:
        resp2 = await service.handle_inbound_message(inbound_during_pause)
        assert resp2 == ""
        mock_send_silent.assert_not_called()

    # 3. Cliente decide retomar o autoatendimento da IA
    inbound_resume = InboundMessage(
        provider="waha",
        sender_phone=phone,
        sender_name="Danilo",
        text="Voltar para o bot",
        message_id="msg-h-3",
    )
    with patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send_resume:
        resp3 = await service.handle_inbound_message(inbound_resume)
        assert resp3 != ""
        mock_send_resume.assert_called_once()


@pytest.mark.asyncio
async def test_seller_ai_transcribes_audio_voice_message(db_session: Session):
    prod = Product(
        name="Pomada Modeladora Efeito Seco",
        price_cents=3500,
        stock_quantity=15,
        active=True,
    )
    db_session.add(prod)
    db_session.commit()

    service = SellerAIService(db_session)
    inbound_audio = InboundMessage(
        provider="evolution",
        sender_phone="5585994445555",
        sender_name="Guilherme",
        text="",
        media_type="audio",
        media_url="https://evolution.api/media/audio123.ogg",
        message_id="msg-audio-1",
    )

    with patch("app.services.whatsapp.transcription_service.AudioTranscriptionService.download_and_transcribe", new_callable=AsyncMock) as mock_transcribe, \
         patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send:

        mock_transcribe.return_value = "Olá, vocês têm pomada modeladora?"
        response = await service.handle_inbound_message(inbound_audio)

        assert "Pomada Modeladora Efeito Seco" in response
        assert "R$ 35.00" in response
        mock_send.assert_called_once()

