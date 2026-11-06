from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.company_settings import CompanySettings


def test_meta_webhook_verification_success(anonymous_client: TestClient, db_session: Session):
    settings = db_session.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(company_name="Teste")
        db_session.add(settings)
    settings.meta_verify_token = "meu_token_secreto"
    db_session.commit()

    response = anonymous_client.get(
        "/api/webhooks/whatsapp/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "meu_token_secreto",
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 200
    assert response.text == "1158201444"


def test_meta_webhook_verification_forbidden_on_wrong_token(
    anonymous_client: TestClient, db_session: Session
):
    settings = db_session.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(company_name="Teste")
        db_session.add(settings)
    settings.meta_verify_token = "meu_token_secreto"
    db_session.commit()

    response = anonymous_client.get(
        "/api/webhooks/whatsapp/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token_errado",
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 403


def test_waha_webhook_post_triggers_seller_ai(anonymous_client: TestClient):
    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "true_5585999998888@c.us_123",
            "from": "5585999998888@c.us",
            "fromMe": False,
            "body": "Quais os produtos disponíveis?",
            "_data": {"notifyName": "Rodrigo"},
        },
    }

    with patch("app.services.seller_ai_service.SellerAIService.handle_inbound_message", new_callable=AsyncMock) as mock_handle:
        response = anonymous_client.post("/api/webhooks/whatsapp/waha", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_handle.assert_called_once()
        inbound = mock_handle.call_args[0][0]
        assert inbound.sender_phone == "5585999998888"
        assert inbound.text == "Quais os produtos disponíveis?"


def test_evolution_webhook_post_triggers_seller_ai(anonymous_client: TestClient):
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "5585988887777@s.whatsapp.net",
                "fromMe": False,
                "id": "evo-123",
            },
            "pushName": "Ana",
            "message": {
                "conversation": "Quero comprar",
            },
        },
    }

    with patch("app.services.seller_ai_service.SellerAIService.handle_inbound_message", new_callable=AsyncMock) as mock_handle:
        response = anonymous_client.post("/api/webhooks/whatsapp/evolution", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_handle.assert_called_once()
        inbound = mock_handle.call_args[0][0]
        assert inbound.sender_phone == "5585988887777"
        assert inbound.text == "Quero comprar"


def test_waha_webhook_duplicate_is_ignored(anonymous_client: TestClient):
    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "waha-duplicate-test-999",
            "from": "5585999998888@c.us",
            "fromMe": False,
            "body": "Quero 5kg de camarão médio",
            "_data": {"notifyName": "Rodrigo"},
        },
    }

    with patch("app.services.seller_ai_service.SellerAIService.handle_inbound_message", new_callable=AsyncMock) as mock_handle:
        # Primeiro envio: deve ser processado normalmente
        res1 = anonymous_client.post("/api/webhooks/whatsapp/waha", json=payload)
        assert res1.status_code == 200
        assert res1.json() == {"status": "ok"}
        assert mock_handle.call_count == 1

        # Segundo envio idêntico (duplicata de webhook): deve ser detectado e ignorado
        res2 = anonymous_client.post("/api/webhooks/whatsapp/waha", json=payload)
        assert res2.status_code == 200
        assert res2.json() == {"status": "ok", "detail": "duplicate_ignored"}
        # O agente NÃO deve ter sido chamado novamente!
        assert mock_handle.call_count == 1


def test_waha_webhook_full_flow_sends_reply(anonymous_client: TestClient, db_session: Session):
    from app.models.product import Product
    from app.services.whatsapp.base import SendMessageResult

    prod = Product(
        name="Luminária Rústica",
        price_cents=15000,
        stock_quantity=5,
        active=True,
    )
    db_session.add(prod)
    db_session.commit()

    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "waha-full-flow-msg-1",
            "from": "5585991112222@c.us",
            "fromMe": False,
            "body": "Olá, gostaria de ver os produtos",
            "_data": {"notifyName": "Mariana"},
        },
    }

    mock_send = AsyncMock(return_value=SendMessageResult(success=True, provider="waha", message_id="sent-123"))

    with patch("app.services.whatsapp.waha.WahaWhatsAppProvider.send_text", mock_send):
        response = anonymous_client.post("/api/webhooks/whatsapp/waha", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert mock_send.call_count >= 1
        called_phone, called_text = mock_send.call_args[0]
        assert "5585991112222" in called_phone
        assert "Luminária Rústica" in called_text


def test_waha_webhook_alias_without_api_prefix_succeeds(anonymous_client: TestClient, db_session: Session):
    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "alias-msg-999",
            "from": "5585993334444@c.us",
            "fromMe": False,
            "body": "Teste rota alias sem /api",
            "_data": {"notifyName": "Alias Test"},
        },
    }

    mock_handle = AsyncMock(return_value="Olá!")
    with patch("app.services.seller_ai_service.SellerAIService.handle_inbound_message", mock_handle):
        response = anonymous_client.post("/webhooks/whatsapp/waha", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert mock_handle.call_count == 1


def test_admin_whatsapp_sync_webhook(client: TestClient):
    from tests.test_admin_login_flow import login, session_data

    login(client)
    csrf = session_data(client)["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    with patch("app.services.whatsapp.waha.WahaWhatsAppProvider.ensure_session_webhook", new_callable=AsyncMock) as mock_sync:
        mock_sync.return_value = {"configured": True, "synced": True, "webhook_url": "http://vendedor-ia:8000/api/webhooks/whatsapp/waha"}
        response = client.post("/admin/api/whatsapp/sync-webhook", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["synced"] is True


def test_admin_whatsapp_test_send(client: TestClient):
    from app.services.whatsapp.base import SendMessageResult
    from tests.test_admin_login_flow import login, session_data

    login(client)
    csrf = session_data(client)["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    mock_send = AsyncMock(return_value=SendMessageResult(success=True, provider="waha", message_id="test-msg-1"))
    with patch("app.services.whatsapp.gateway.WhatsAppGatewayService.send_text", mock_send):
        response = client.post(
            "/admin/api/whatsapp/test-send",
            json={"phone": "5511999998888", "text": "Teste de envio"},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message_id"] == "test-msg-1"



