import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.orm import Session

from app.models.company_settings import CompanySettings
from app.services.seller_ai_service import SellerAIService
from app.services.whatsapp.base import InboundMessage
from app.services.whatsapp.meta import MetaWhatsAppProvider
from app.services.whatsapp.transcription_service import AudioTranscriptionService
from app.services.whatsapp.waha import WahaWhatsAppProvider

FAKE_OGG_BYTES = b"OggS" + b"\x00\x02" + (b"\x11" * 180)


def _get_or_create_settings(db: Session) -> CompanySettings:
    settings = db.query(CompanySettings).first()
    if not settings:
        settings = CompanySettings(company_name="Loja Audio Teste")
        db.add(settings)
        db.commit()
    return settings


@pytest.mark.asyncio
async def test_transcribe_via_openrouter_input_audio(db_session: Session):
    settings = _get_or_create_settings(db_session)
    settings.ai_provider = "openrouter"
    settings.ai_api_key = "sk-or-v1-test-key"
    db_session.commit()

    service = AudioTranscriptionService(db_session)

    mock_resp = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "Quero dois quilos de camarão grande"}}]},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        text = await service.transcribe_audio_bytes(
            FAKE_OGG_BYTES, mimetype="audio/ogg; codecs=opus"
        )

    assert text == "Quero dois quilos de camarão grande"
    mock_post.assert_called_once()
    call_url = mock_post.call_args[0][0]
    call_json = mock_post.call_args[1]["json"]
    assert call_url == "https://openrouter.ai/api/v1/chat/completions"
    assert call_json["model"] == "google/gemini-2.5-flash"
    content_parts = call_json["messages"][0]["content"]
    audio_part = next(p for p in content_parts if p["type"] == "input_audio")
    assert audio_part["input_audio"]["format"] == "ogg"
    assert base64.b64decode(audio_part["input_audio"]["data"]) == FAKE_OGG_BYTES


@pytest.mark.asyncio
async def test_transcribe_via_gemini_native_inline_data(db_session: Session):
    settings = _get_or_create_settings(db_session)
    settings.ai_provider = "gemini"
    settings.ai_api_key = "AIzaTestGeminiKey123"
    db_session.commit()

    service = AudioTranscriptionService(db_session)

    mock_resp = httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": "Qual o horário de entrega?"}]}}
            ]
        },
        request=httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        ),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        text = await service.transcribe_audio_bytes(FAKE_OGG_BYTES)

    assert text == "Qual o horário de entrega?"
    call_url = mock_post.call_args[0][0]
    call_headers = mock_post.call_args[1]["headers"]
    assert "generativelanguage.googleapis.com" in call_url
    assert call_headers["x-goog-api-key"] == "AIzaTestGeminiKey123"


@pytest.mark.asyncio
async def test_anthropic_primary_cascades_to_openrouter_env_key(
    db_session: Session, monkeypatch
):
    settings = _get_or_create_settings(db_session)
    settings.ai_provider = "anthropic"
    settings.ai_api_key = "sk-ant-test-key"
    db_session.commit()

    monkeypatch.setattr("app.services.whatsapp.transcription_service.app_settings.groq_api_key", "")
    monkeypatch.setattr("app.services.whatsapp.transcription_service.app_settings.openai_api_key", "")
    monkeypatch.setattr("app.services.whatsapp.transcription_service.app_settings.gemini_api_key", "")
    monkeypatch.setattr(
        "app.services.whatsapp.transcription_service.app_settings.openrouter_api_key",
        "sk-or-v1-env-fallback",
    )

    service = AudioTranscriptionService(db_session)
    candidates = service._resolve_transcription_candidates()
    assert [c[0] for c in candidates] == ["openrouter"]
    assert candidates[0][1] == "sk-or-v1-env-fallback"


@pytest.mark.asyncio
async def test_primary_failure_cascades_to_fallback_provider(
    db_session: Session, monkeypatch
):
    settings = _get_or_create_settings(db_session)
    settings.ai_provider = "openai"
    settings.ai_api_key = "sk-openai-bad-key"
    db_session.commit()

    monkeypatch.setattr("app.services.whatsapp.transcription_service.app_settings.groq_api_key", "gsk_fallback_key")
    monkeypatch.setattr("app.services.whatsapp.transcription_service.app_settings.openai_api_key", "")
    monkeypatch.setattr("app.services.whatsapp.transcription_service.app_settings.gemini_api_key", "")
    monkeypatch.setattr("app.services.whatsapp.transcription_service.app_settings.openrouter_api_key", "")

    service = AudioTranscriptionService(db_session)

    fail_resp = httpx.Response(
        401,
        text="Invalid API key",
        request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions"),
    )
    ok_resp = httpx.Response(
        200,
        json={"text": "Transcrição via fallback Groq"},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [fail_resp, ok_resp]
        text = await service.transcribe_audio_bytes(FAKE_OGG_BYTES)

    assert text == "Transcrição via fallback Groq"
    assert mock_post.call_count == 2
    assert "api.openai.com" in mock_post.call_args_list[0][0][0]
    assert "api.groq.com" in mock_post.call_args_list[1][0][0]


def test_waha_loopback_media_url_rewrite_and_auth_headers(db_session: Session):
    settings = _get_or_create_settings(db_session)
    settings.whatsapp_provider = "waha"
    settings.waha_base_url = "http://waha:3000"
    settings.waha_api_key = "waha-secret-key"
    db_session.commit()

    service = AudioTranscriptionService(db_session)

    rewritten = service._normalize_media_url(
        "http://localhost:3000/api/files/default/voice.oga", provider="waha"
    )
    assert rewritten == "http://waha:3000/api/files/default/voice.oga"
    assert service._is_safe_audio_url(rewritten) is True
    assert service._build_provider_auth_headers(rewritten, provider="waha") == {
        "X-Api-Key": "waha-secret-key"
    }

    # Nunca envia X-Api-Key para hosts externos e bloqueia metadata SSRF
    assert service._build_provider_auth_headers("https://cdn.example.com/audio.ogg", provider="waha") == {}
    assert service._is_safe_audio_url("http://169.254.169.254/latest/meta-data/") is False


def test_waha_and_meta_parse_audio_webhooks():
    waha = WahaWhatsAppProvider(base_url="http://waha:3000")
    waha_payload = {
        "event": "message.any",
        "payload": {
            "id": "false_5585999991234@c.us_AUDIO1",
            "from": "5585999991234@c.us",
            "fromMe": False,
            "hasMedia": True,
            "type": "ptt",
            "media": {
                "url": "http://localhost:3000/api/files/default/voice.oga",
                "mimetype": "audio/ogg; codecs=opus",
            },
        },
    }
    waha_inbound = waha.parse_inbound_webhook(waha_payload)
    assert waha_inbound is not None
    assert waha_inbound.media_type == "audio"
    assert waha_inbound.media_url == "http://localhost:3000/api/files/default/voice.oga"
    assert waha_inbound.media_mimetype == "audio/ogg; codecs=opus"

    meta = MetaWhatsAppProvider(phone_number_id="12345", access_token="meta-tok")
    meta_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": "5585900000000"},
                            "contacts": [{"profile": {"name": "Joana"}}],
                            "messages": [
                                {
                                    "from": "5585999995678",
                                    "id": "wamid.AUDIO99",
                                    "type": "audio",
                                    "audio": {"id": "media_998877", "mime_type": "audio/ogg; codecs=opus"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    meta_inbound = meta.parse_inbound_webhook(meta_payload)
    assert meta_inbound is not None
    assert meta_inbound.media_type == "audio"
    assert meta_inbound.media_url == "meta-media://media_998877"
    assert meta_inbound.media_mimetype == "audio/ogg; codecs=opus"


@pytest.mark.asyncio
async def test_seller_ai_graceful_fallback_when_audio_cannot_be_transcribed(db_session: Session):
    service = SellerAIService(db_session)
    inbound = InboundMessage(
        provider="waha",
        sender_phone="5585991234567",
        sender_name="Paulo",
        text="[Mensagem de áudio recebida]",
        message_id="msg-audio-fail-1",
        media_type="audio",
        media_url="http://waha:3000/api/files/default/broken.oga",
        media_mimetype="audio/ogg",
    )

    with patch(
        "app.services.whatsapp.transcription_service.AudioTranscriptionService.download_and_transcribe",
        new_callable=AsyncMock,
        return_value=None,
    ), patch.object(service.gateway, "send_text", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = MagicMock(success=True, message_id="sent-1")
        reply = await service.handle_inbound_message(inbound)

    assert "não consegui ouvir" in reply.lower()
    assert "texto" in reply.lower()
    mock_send.assert_called_once()
