from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.company_settings import CompanySettings
from app.models.user import User
from app.services.seller_ai_service import SellerAIService
from app.services.whatsapp.base import InboundMessage
from app.services.whatsapp.evolution import EvolutionWhatsAppProvider
from app.services.whatsapp.gateway import WhatsAppGatewayService
from app.services.whatsapp.meta import MetaWhatsAppProvider
from app.services.whatsapp.tracker import SentMessageTracker


@pytest.fixture(autouse=True)
def clean_tracker():
    tracker = SentMessageTracker.get_instance()
    tracker.clear()
    yield
    tracker.clear()


def test_sent_message_tracker():
    tracker = SentMessageTracker.get_instance()
    assert tracker.is_bot_message("msg-abc") is False

    tracker.record("msg-abc")
    assert tracker.is_bot_message("msg-abc") is True
    assert tracker.is_bot_message("msg-xyz") is False


@pytest.mark.asyncio
async def test_gateway_send_text_registers_in_tracker(db_session: Session):
    settings = db_session.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(company_name="Loja Teste")
        db_session.add(settings)
    settings.whatsapp_provider = "evolution"
    settings.evolution_base_url = "http://evolution:8080"
    settings.evolution_instance = "default"
    db_session.commit()

    gateway = WhatsAppGatewayService(db_session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"key": {"id": "msg-bot-out-1"}}
    mock_resp.text = '{"key": {"id": "msg-bot-out-1"}}'

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await gateway.send_text("5585988887777", "Olá do bot!")
        assert res.success is True
        assert res.message_id == "msg-bot-out-1"
        assert SentMessageTracker.get_instance().is_bot_message("msg-bot-out-1") is True


def test_evolution_parses_from_me_for_coexistence():
    provider = EvolutionWhatsAppProvider(base_url="http://evolution:8080", instance="default")
    payload = {
        "event": "messages.upsert",
        "instance": "default",
        "data": {
            "key": {
                "remoteJid": "5585991112233@s.whatsapp.net",
                "fromMe": True,
                "id": "evo-human-100",
            },
            "pushName": "Vendedor Carlos",
            "message": {
                "conversation": "Olá dona Maria! Separei seu pedido aqui na loja.",
            },
        },
    }
    inbound = provider.parse_inbound_webhook(payload)
    assert inbound is not None
    assert inbound.is_from_me is True
    assert inbound.sender_phone == "5585991112233"
    assert inbound.text == "Olá dona Maria! Separei seu pedido aqui na loja."
    assert inbound.message_id == "evo-human-100"


def test_meta_parses_echo_for_coexistence():
    provider = MetaWhatsAppProvider(phone_number_id="12345", access_token="token")
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5585990001111",
                                "phone_number_id": "12345",
                            },
                            "messages": [
                                {
                                    "from": "5585990001111",
                                    "to": "5585988889999",
                                    "id": "wamid.ECHO123",
                                    "is_echo": True,
                                    "type": "text",
                                    "text": {"body": "Seu pedido está a caminho!"},
                                }
                            ],
                        }
                    }
                ],
            }
        ],
    }
    inbound = provider.parse_inbound_webhook(payload)
    assert inbound is not None
    assert inbound.is_from_me is True
    assert inbound.sender_phone == "5585988889999"
    assert inbound.text == "Seu pedido está a caminho!"


@pytest.mark.asyncio
async def test_human_agent_message_pauses_ia_and_saves_history(db_session: Session):
    settings = db_session.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(company_name="Loja Teste")
        db_session.add(settings)
    settings.coexistence_enabled = True
    settings.coexistence_pause_minutes = 45
    db_session.commit()

    phone = "5585977778888"
    service = SellerAIService(db_session)

    # Atendente humano digita pelo WhatsApp Business no celular
    inbound = InboundMessage(
        provider="evolution",
        sender_phone=phone,
        sender_name="Atendente",
        text="Oi! Já estou verificando seu pedido aqui no balcão.",
        message_id="msg-human-1",
        is_from_me=True,
    )

    with patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send:
        resp = await service.handle_inbound_message(inbound)
        assert resp == ""
        mock_send.assert_not_called()

    # Verifica se o usuário teve a IA pausada por ~45 minutos
    user = db_session.query(User).filter(User.phone == phone).first()
    assert user is not None
    custom = user.custom_fields or {}
    paused_until_str = custom.get("ai_paused_until")
    assert paused_until_str is not None
    paused_until = datetime.fromisoformat(paused_until_str)
    if paused_until.tzinfo is None:
        paused_until = paused_until.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    assert paused_until > now + timedelta(minutes=40)

    # Verifica se mensagem foi salva no histórico como 'human_agent'
    chat_msg = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.phone == phone, ChatMessage.role == "human_agent")
        .first()
    )
    assert chat_msg is not None
    assert chat_msg.content == "Oi! Já estou verificando seu pedido aqui no balcão."


@pytest.mark.asyncio
async def test_customer_reply_during_pause_is_silenced(db_session: Session):
    phone = "5585977778888"
    user = db_session.query(User).filter(User.phone == phone).first()
    if not user:
        user = User(name="Cliente Teste", phone=phone)
        db_session.add(user)
    # Pausa ativa por mais 30 minutos
    user.custom_fields = {
        "ai_paused_until": (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    }
    db_session.commit()

    service = SellerAIService(db_session)
    inbound_customer = InboundMessage(
        provider="evolution",
        sender_phone=phone,
        sender_name="Cliente",
        text="Perfeito, fico no aguardo!",
        message_id="msg-cust-2",
        is_from_me=False,
    )

    with patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send:
        resp = await service.handle_inbound_message(inbound_customer)
        assert resp == ""
        mock_send.assert_not_called()

    # Confirma que a mensagem do cliente foi registrada no histórico
    chat_msg = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.phone == phone, ChatMessage.content == "Perfeito, fico no aguardo!")
        .first()
    )
    assert chat_msg is not None
    assert chat_msg.role == "user"


@pytest.mark.asyncio
async def test_human_agent_commands_unpause_and_pause(db_session: Session):
    phone = "5585977778888"
    user = db_session.query(User).filter(User.phone == phone).first()
    if not user:
        user = User(name="Cliente Teste", phone=phone)
        db_session.add(user)
    user.custom_fields = {
        "ai_paused_until": (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    }
    db_session.commit()

    service = SellerAIService(db_session)

    # 1. Atendente digita #bot para devolver o atendimento para a IA
    inbound_unpause = InboundMessage(
        provider="evolution",
        sender_phone=phone,
        sender_name="Atendente",
        text="#bot",
        message_id="msg-cmd-1",
        is_from_me=True,
    )
    await service.handle_inbound_message(inbound_unpause)

    db_session.refresh(user)
    assert user.custom_fields.get("ai_paused_until") is None

    # 2. Atendente digita #pausa para travar por 4 horas
    inbound_pause = InboundMessage(
        provider="evolution",
        sender_phone=phone,
        sender_name="Atendente",
        text="#pausa",
        message_id="msg-cmd-2",
        is_from_me=True,
    )
    await service.handle_inbound_message(inbound_pause)

    db_session.refresh(user)
    paused_until_str = user.custom_fields.get("ai_paused_until")
    assert paused_until_str is not None
    paused_until = datetime.fromisoformat(paused_until_str)
    if paused_until.tzinfo is None:
        paused_until = paused_until.replace(tzinfo=UTC)
    assert paused_until > datetime.now(UTC) + timedelta(hours=3, minutes=50)


@pytest.mark.asyncio
async def test_bot_echo_does_not_pause_ia(db_session: Session):
    phone = "5585966665555"
    service = SellerAIService(db_session)

    # Registra que o bot enviou uma mensagem com ID msg-bot-123
    SentMessageTracker.get_instance().record("msg-bot-123")

    # Chega o eco no webhook (fromMe: true)
    inbound_echo = InboundMessage(
        provider="evolution",
        sender_phone=phone,
        sender_name="Atendente",
        text="Olá, sou o assistente virtual!",
        message_id="msg-bot-123",
        is_from_me=True,
    )

    resp = await service.handle_inbound_message(inbound_echo)
    assert resp == ""

    # Verifica que o usuário NÃO foi pausado
    user = db_session.query(User).filter(User.phone == phone).first()
    if user:
        custom = user.custom_fields or {}
        assert custom.get("ai_paused_until") is None
