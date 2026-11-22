from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.company_settings import CompanySettings
from app.services.whatsapp.evolution import EvolutionWhatsAppProvider
from app.services.whatsapp.gateway import WhatsAppGatewayService
from app.services.whatsapp.meta import MetaWhatsAppProvider
from app.services.whatsapp.waha import WahaWhatsAppProvider


def test_waha_parse_inbound_webhook():
    provider = WahaWhatsAppProvider(base_url="http://waha:3000")

    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "true_5585999998888@c.us_3EB012345",
            "from": "5585999998888@c.us",
            "fromMe": False,
            "body": "Olá, quanto custa o produto?",
            "_data": {
                "notifyName": "Carlos Silva",
            },
        },
    }

    inbound = provider.parse_inbound_webhook(payload)
    assert inbound is not None
    assert inbound.provider == "waha"
    assert inbound.sender_phone == "5585999998888"
    assert inbound.sender_name == "Carlos Silva"
    assert inbound.text == "Olá, quanto custa o produto?"
    assert inbound.message_id == "true_5585999998888@c.us_3EB012345"


def test_waha_parses_from_me_messages_for_coexistence():
    provider = WahaWhatsAppProvider(base_url="http://waha:3000")
    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "false_5585999998888@c.us_3EB012345",
            "to": "5585999998888@c.us",
            "fromMe": True,
            "body": "Mensagem enviada pelo atendente humano",
        },
    }
    inbound = provider.parse_inbound_webhook(payload)
    assert inbound is not None
    assert inbound.is_from_me is True
    assert inbound.sender_phone == "5585999998888"
    assert inbound.sender_name == "Atendente"
    assert inbound.text == "Mensagem enviada pelo atendente humano"


@pytest.mark.asyncio
async def test_waha_send_text_success():
    provider = WahaWhatsAppProvider(base_url="http://waha:3000", api_key="secret-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"id": "msg-1234"}'
    mock_resp.json.return_value = {"id": "msg-1234"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await provider.send_text("5585999998888", "Olá!")

        assert result.success is True
        assert result.message_id == "msg-1234"
        assert result.provider == "waha"

        call_args = mock_post.call_args
        assert "http://waha:3000/api/sendText" in call_args[0]
        assert call_args[1]["json"]["chatId"] == "5585999998888@c.us"
        assert call_args[1]["headers"]["X-Api-Key"] == "secret-key"


def test_evolution_parse_inbound_webhook():
    provider = EvolutionWhatsAppProvider(base_url="http://evolution:8080", instance="default")

    payload = {
        "event": "messages.upsert",
        "instance": "default",
        "data": {
            "key": {
                "remoteJid": "5585988887777@s.whatsapp.net",
                "fromMe": False,
                "id": "evo-msg-999",
            },
            "pushName": "Mariana",
            "message": {
                "conversation": "Gostaria de ver o catálogo",
            },
        },
    }

    inbound = provider.parse_inbound_webhook(payload)
    assert inbound is not None
    assert inbound.provider == "evolution"
    assert inbound.sender_phone == "5585988887777"
    assert inbound.sender_name == "Mariana"
    assert inbound.text == "Gostaria de ver o catálogo"


@pytest.mark.asyncio
async def test_evolution_send_text_success():
    provider = EvolutionWhatsAppProvider(
        base_url="http://evolution:8080", instance="loja1", api_key="evo-key"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"key": {"id": "msg-evo-1"}}'
    mock_resp.json.return_value = {"key": {"id": "msg-evo-1"}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await provider.send_text("5585988887777", "Olá, bem-vindo!")

        assert result.success is True
        assert result.message_id == "msg-evo-1"
        assert result.provider == "evolution"


def test_meta_parse_inbound_webhook():
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
                            "metadata": {"phone_number_id": "12345"},
                            "contacts": [{"profile": {"name": "Fernanda"}}],
                            "messages": [
                                {
                                    "from": "5585977776666",
                                    "id": "wamid.ABCDEF123",
                                    "type": "text",
                                    "text": {"body": "Quero comprar o produto #1"},
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
    assert inbound.provider == "meta"
    assert inbound.sender_phone == "5585977776666"
    assert inbound.sender_name == "Fernanda"
    assert inbound.text == "Quero comprar o produto #1"
    assert inbound.message_id == "wamid.ABCDEF123"


def test_gateway_service_selects_active_provider(db_session):
    settings = db_session.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(company_name="Teste")
        db_session.add(settings)

    settings.whatsapp_provider = "waha"
    settings.waha_base_url = "http://waha-local:3000"
    settings.waha_session = "vendas"
    db_session.commit()

    gateway = WhatsAppGatewayService(db_session)
    provider = gateway.get_provider()
    assert isinstance(provider, WahaWhatsAppProvider)
    assert provider.name == "waha"
    assert provider.base_url == "http://waha-local:3000"
    assert provider.session == "vendas"

    settings.whatsapp_provider = "meta"
    settings.meta_phone_number_id = "meta-100"
    settings.meta_access_token = "meta-token-xyz"
    db_session.commit()

    gateway2 = WhatsAppGatewayService(db_session)
    provider2 = gateway2.get_provider()
    assert isinstance(provider2, MetaWhatsAppProvider)
    assert provider2.phone_number_id == "meta-100"


def test_waha_parse_inbound_with_lid_and_remote_jid_alt():
    provider = WahaWhatsAppProvider(base_url="http://waha:3000")
    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "false_102228962623501@lid_3EB012345",
            "from": "102228962623501@lid",
            "body": "Olá via LID com remoteJidAlt",
            "_data": {
                "notifyName": "Cliente VIP",
                "key": {
                    "remoteJid": "102228962623501@lid",
                    "remoteJidAlt": "5585988887777@s.whatsapp.net",
                },
            },
        },
    }
    inbound = provider.parse_inbound_webhook(payload)
    assert inbound is not None
    assert inbound.sender_phone == "5585988887777"
    assert inbound.sender_name == "Cliente VIP"


def test_waha_parse_inbound_with_pure_lid():
    provider = WahaWhatsAppProvider(base_url="http://waha:3000")
    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "false_102228962623501@lid_3EB012345",
            "from": "102228962623501@lid",
            "body": "Olá via pure LID",
            "_data": {
                "notifyName": "Cliente Anon",
            },
        },
    }
    inbound = provider.parse_inbound_webhook(payload)
    assert inbound is not None
    assert inbound.sender_phone == "102228962623501@lid"
    assert provider._format_chat_id(inbound.sender_phone) == "102228962623501@lid"
    assert provider._format_chat_id("102228962623501") == "102228962623501@lid"
    assert provider._format_chat_id("5585999998888") == "5585999998888@c.us"


@pytest.mark.asyncio
async def test_waha_ensure_session_webhook_syncs_missing():
    provider = WahaWhatsAppProvider(base_url="http://agenda_waha:3000")

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {
        "name": "default",
        "status": "WORKING",
        "config": {"webhooks": []},
    }

    mock_put_resp = MagicMock()
    mock_put_resp.status_code = 200
    mock_put_resp.json.return_value = {"success": True}

    client = MagicMock()
    client.get = AsyncMock(return_value=mock_get_resp)
    client.put = AsyncMock(return_value=mock_put_resp)

    res = await provider.ensure_session_webhook(client=client)
    assert res["configured"] is True
    assert res.get("synced") is True
    assert client.put.call_count == 1
    put_call_args = client.put.call_args
    assert "http://vendedor-ia:8000/api/webhooks/whatsapp/waha" in str(put_call_args)


@pytest.mark.asyncio
async def test_waha_ensure_session_webhook_skips_when_already_synced():
    provider = WahaWhatsAppProvider(base_url="http://agenda_waha:3000")

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {
        "name": "default",
        "status": "WORKING",
        "config": {
            "webhooks": [
                {
                    "url": "http://vendedor-ia:8000/api/webhooks/whatsapp/waha",
                    "events": ["message", "message.any"],
                }
            ]
        },
    }

    client = MagicMock()
    client.get = AsyncMock(return_value=mock_get_resp)
    client.put = AsyncMock()

    res = await provider.ensure_session_webhook(client=client)
    assert res["configured"] is True
    assert res.get("already_synced") is True
    assert client.put.call_count == 0


def test_waha_ignores_status_broadcast_even_with_participant_alt():
    provider = WahaWhatsAppProvider(base_url="http://waha:3000")
    payload = {
        "event": "message.any",
        "session": "default",
        "payload": {
            "id": "false_status@broadcast_3EB0STATUS123",
            "from": "status@broadcast",
            "fromMe": False,
            "body": "Bom dia pessoal!",
            "_data": {
                "notifyName": "Contato da Agenda",
                "key": {
                    "remoteJid": "status@broadcast",
                    "participant": "102228962623501@lid",
                    "participantAlt": "5585999991111@s.whatsapp.net",
                },
            },
        },
    }
    assert provider.parse_inbound_webhook(payload) is None


def test_waha_ignores_group_message_even_with_participant_alt():
    provider = WahaWhatsAppProvider(base_url="http://waha:3000")
    payload = {
        "event": "message.any",
        "session": "default",
        "payload": {
            "id": "false_120363000000000@g.us_3EB0GRP123",
            "from": "120363000000000@g.us",
            "fromMe": False,
            "body": "Alguém sabe o preço?",
            "_data": {
                "notifyName": "Membro do Grupo",
                "key": {
                    "remoteJid": "120363000000000@g.us",
                    "participant": "102228962623501@lid",
                    "participantAlt": "5585999992222@s.whatsapp.net",
                },
            },
        },
    }
    assert provider.parse_inbound_webhook(payload) is None


def test_waha_ignores_newsletter_protocol_and_empty_non_audio_media():
    provider = WahaWhatsAppProvider(base_url="http://waha:3000")

    newsletter_payload = {
        "event": "message",
        "payload": {
            "id": "false_120363000@newsletter_1",
            "from": "120363000@newsletter",
            "fromMe": False,
            "body": "Novidades do canal",
        },
    }
    assert provider.parse_inbound_webhook(newsletter_payload) is None

    reaction_payload = {
        "event": "message.any",
        "payload": {
            "id": "false_5585999993333@c.us_REACT1",
            "from": "5585999993333@c.us",
            "fromMe": False,
            "type": "reaction",
            "body": "👍",
        },
    }
    assert provider.parse_inbound_webhook(reaction_payload) is None

    empty_sticker_payload = {
        "event": "message",
        "payload": {
            "id": "false_5585999993333@c.us_STK1",
            "from": "5585999993333@c.us",
            "fromMe": False,
            "hasMedia": True,
            "body": "",
            "media": {"mimetype": "image/webp"},
        },
    }
    assert provider.parse_inbound_webhook(empty_sticker_payload) is None


def test_evolution_ignores_status_broadcast_and_newsletter():
    provider = EvolutionWhatsAppProvider(base_url="http://evolution:8080", instance="default")
    for jid in ("status@broadcast", "120363000@newsletter", "120363000@g.us"):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {"remoteJid": jid, "fromMe": False, "id": "evo-ignore-1"},
                "message": {"conversation": "Texto qualquer"},
            },
        }
        assert provider.parse_inbound_webhook(payload) is None


def test_waha_default_webhook_config_ignores_non_direct_chats_and_sets_hmac():
    provider = WahaWhatsAppProvider(base_url="http://waha:3000", api_key="waha-hmac-secret")
    cfg = provider._default_webhook_config()
    assert cfg["ignore"] == {
        "status": True,
        "groups": True,
        "channels": True,
        "broadcast": True,
    }
    assert cfg["webhooks"][0]["hmac"] == {"key": "waha-hmac-secret"}



