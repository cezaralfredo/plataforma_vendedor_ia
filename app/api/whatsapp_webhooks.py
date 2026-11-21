import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.config import settings as global_settings
from app.database import get_db
from app.models.company_settings import CompanySettings
from app.services.company_settings_service import CompanySettingsService
from app.services.seller_ai_service import SellerAIService
from app.services.whatsapp.deduplicator import InboundDeduplicator
from app.services.whatsapp.gateway import WhatsAppGatewayService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/webhooks/whatsapp",
    tags=["whatsapp-webhooks"],
)


def _is_debug_mode(request: Request) -> bool:
    app_settings = getattr(getattr(request, "app", None), "state", None)
    configured = getattr(app_settings, "settings", None) or global_settings
    return bool(getattr(configured, "debug", False))


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def _verify_meta_post_signature(
    request: Request,
    raw_body: bytes,
    company_settings: CompanySettings,
) -> None:
    custom = company_settings.custom_settings or {}
    app_secret = (
        os.getenv("META_APP_SECRET", "").strip()
        or str(custom.get("meta_app_secret") or "").strip()
    )
    if not app_secret:
        if not _is_debug_mode(request):
            logger.error("META_APP_SECRET não configurado em produção; rejeitando webhook Meta.")
            raise HTTPException(status_code=401, detail="Webhook signature not configured")
        return

    signature_header = request.headers.get("x-hub-signature-256", "").strip()
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing or invalid Meta signature")
    supplied_sig = signature_header.split("=", 1)[1].strip()
    expected_sig = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied_sig, expected_sig):
        logger.warning("Assinatura HMAC-SHA256 inválida no webhook da Meta.")
        raise HTTPException(status_code=401, detail="Invalid Meta signature")


def _verify_provider_webhook_auth(
    request: Request,
    provider: str,
    raw_body: bytes,
    company_settings: CompanySettings,
) -> None:
    shared_secret = os.getenv("WHATSAPP_WEBHOOK_SECRET", "").strip()
    expected_secrets: list[str] = []
    if shared_secret:
        expected_secrets.append(shared_secret)

    if provider == "waha":
        waha_key = (company_settings.waha_api_key or os.getenv("WAHA_API_KEY") or "").strip()
        if waha_key:
            expected_secrets.append(waha_key)
    elif provider == "evolution":
        evo_key = (company_settings.evolution_api_key or os.getenv("EVOLUTION_API_KEY") or "").strip()
        if evo_key:
            expected_secrets.append(evo_key)
    else:
        for candidate in (
            company_settings.waha_api_key,
            os.getenv("WAHA_API_KEY"),
            company_settings.evolution_api_key,
            os.getenv("EVOLUTION_API_KEY"),
        ):
            if candidate and candidate.strip():
                expected_secrets.append(candidate.strip())

    if not expected_secrets:
        if not _is_debug_mode(request):
            logger.error("Segredo de webhook WhatsApp (%s) ausente em produção.", provider)
            raise HTTPException(status_code=401, detail="Webhook authentication not configured")
        return

    supplied_candidates = [
        request.headers.get("x-webhook-secret", "").strip(),
        request.headers.get("x-api-key", "").strip(),
        request.headers.get("apikey", "").strip(),
        _extract_bearer_token(request),
    ]
    for supplied in supplied_candidates:
        if supplied and any(hmac.compare_digest(supplied, secret) for secret in expected_secrets):
            return

    # Suporte nativo ao header HMAC do WAHA (X-Webhook-Hmac / SHA-512)
    hmac_header = request.headers.get("x-webhook-hmac", "").strip()
    if hmac_header:
        algo_name = request.headers.get("x-webhook-hmac-algorithm", "sha512").lower().strip()
        digest_mod = hashlib.sha256 if algo_name == "sha256" else hashlib.sha512
        for secret in expected_secrets:
            expected_hmac = hmac.new(secret.encode("utf-8"), raw_body, digest_mod).hexdigest()
            if hmac.compare_digest(hmac_header, expected_hmac):
                return

    logger.warning("Webhook WhatsApp (%s) rejeitado: credencial ausente ou inválida.", provider)
    raise HTTPException(status_code=401, detail="Unauthorized webhook request")


async def _parse_json_body(request: Request) -> tuple[bytes, dict[str, Any]]:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")
    return raw_body, payload


@router.get("/meta")
@router.get("/meta/")
async def verify_meta_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    db: Session = Depends(get_db),
):
    """Verificação do Webhook da Meta Cloud API (GET challenge)."""
    settings = CompanySettingsService(db).get_or_create_default()
    expected_token = settings.meta_verify_token

    if hub_mode == "subscribe":
        if not expected_token or not hmac.compare_digest(hub_verify_token or "", expected_token):
            logger.warning("Falha na verificação da Meta: verify_token inválido.")
            raise HTTPException(status_code=403, detail="Verification token mismatch")
        logger.info("Webhook da Meta verificado com sucesso.")
        return Response(content=hub_challenge or "", media_type="text/plain")

    raise HTTPException(status_code=400, detail="Invalid hub.mode")


@router.post("/meta")
@router.post("/meta/")
async def handle_meta_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Webhook para mensagens recebidas da Meta Cloud API Oficial."""
    raw_body, payload = await _parse_json_body(request)
    company_settings = CompanySettingsService(db).get_or_create_default()
    _verify_meta_post_signature(request, raw_body, company_settings)

    gateway = WhatsAppGatewayService(db)
    inbound = gateway.parse_inbound("meta", payload)

    if inbound:
        deduplicator = InboundDeduplicator.get_instance()
        if not deduplicator.try_acquire(db, inbound.message_id, inbound.provider, inbound.sender_phone):
            return {"status": "ok", "detail": "duplicate_ignored"}

        seller_ai = SellerAIService(db)
        try:
            await seller_ai.handle_inbound_message(inbound)
        except Exception as exc:
            logger.exception("Erro ao processar mensagem da Meta Cloud API: %s", exc)

    return {"status": "ok"}


@router.post("/waha")
@router.post("/waha/")
async def handle_waha_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Webhook para mensagens recebidas do WAHA (WhatsApp HTTP API)."""
    raw_body, payload = await _parse_json_body(request)
    company_settings = CompanySettingsService(db).get_or_create_default()
    _verify_provider_webhook_auth(request, "waha", raw_body, company_settings)

    event = payload.get("event")
    logger.info("WAHA webhook recebido: event=%s", event)

    gateway = WhatsAppGatewayService(db)
    inbound = gateway.parse_inbound("waha", payload)

    if not inbound:
        logger.debug("WAHA webhook ignorado (não gerou mensagem de entrada elegível)")
        return {"status": "ok", "detail": "ignored_non_message"}

    deduplicator = InboundDeduplicator.get_instance()
    if not deduplicator.try_acquire(db, inbound.message_id, inbound.provider, inbound.sender_phone):
        logger.info(
            "WAHA webhook ignorado por deduplicação: msg_id=%s, fone=%s",
            inbound.message_id,
            inbound.sender_phone,
        )
        return {"status": "ok", "detail": "duplicate_ignored"}

    logger.info(
        "WAHA mensagem aceita para processamento: de=%s (%s), texto='%s'",
        inbound.sender_phone,
        inbound.sender_name,
        inbound.text[:120],
    )
    seller_ai = SellerAIService(db)
    try:
        reply = await seller_ai.handle_inbound_message(inbound)
        logger.info(
            "WAHA resposta concluída para %s (tamanho=%d)",
            inbound.sender_phone,
            len(reply) if reply else 0,
        )
    except Exception as exc:
        logger.exception("Erro ao processar mensagem do WAHA (%s): %s", inbound.message_id, exc)

    return {"status": "ok"}


@router.post("/evolution")
@router.post("/evolution/")
async def handle_evolution_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Webhook para mensagens recebidas da Evolution API."""
    raw_body, payload = await _parse_json_body(request)
    company_settings = CompanySettingsService(db).get_or_create_default()
    _verify_provider_webhook_auth(request, "evolution", raw_body, company_settings)

    gateway = WhatsAppGatewayService(db)
    inbound = gateway.parse_inbound("evolution", payload)

    if inbound:
        deduplicator = InboundDeduplicator.get_instance()
        if not deduplicator.try_acquire(db, inbound.message_id, inbound.provider, inbound.sender_phone):
            return {"status": "ok", "detail": "duplicate_ignored"}

        seller_ai = SellerAIService(db)
        try:
            await seller_ai.handle_inbound_message(inbound)
        except Exception as exc:
            logger.exception("Erro ao processar mensagem da Evolution API (%s): %s", inbound.message_id, exc)

    return {"status": "ok"}


@router.post("/inbound")
@router.post("/inbound/")
async def handle_generic_inbound_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Webhook genérico que utiliza o provedor ativo configurado na empresa."""
    raw_body, payload = await _parse_json_body(request)
    company_settings = CompanySettingsService(db).get_or_create_default()
    _verify_provider_webhook_auth(request, "inbound", raw_body, company_settings)

    gateway = WhatsAppGatewayService(db)
    active_provider = gateway.settings.whatsapp_provider or "evolution"
    inbound = gateway.parse_inbound(active_provider, payload)

    # Fallback de parser caso o payload seja de outro formato conhecido
    if not inbound:
        for alt_provider in ("waha", "evolution", "meta"):
            if alt_provider != active_provider:
                inbound = gateway.parse_inbound(alt_provider, payload)
                if inbound:
                    break

    if inbound:
        deduplicator = InboundDeduplicator.get_instance()
        if not deduplicator.try_acquire(db, inbound.message_id, inbound.provider, inbound.sender_phone):
            return {"status": "ok", "provider": active_provider, "detail": "duplicate_ignored"}

        seller_ai = SellerAIService(db)
        try:
            await seller_ai.handle_inbound_message(inbound)
        except Exception as exc:
            logger.exception("Erro ao processar mensagem genérica inbound (%s): %s", inbound.message_id, exc)

    return {"status": "ok", "provider": active_provider}
