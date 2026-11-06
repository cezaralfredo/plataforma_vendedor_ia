import asyncio
import base64
import logging
import re
from typing import Any

import httpx

from app.services.whatsapp.base import (
    BaseWhatsAppProvider,
    InboundMessage,
    SendMessageResult,
)

logger = logging.getLogger(__name__)


class WahaWhatsAppProvider(BaseWhatsAppProvider):
    name: str = "waha"

    def __init__(
        self,
        base_url: str | None,
        session: str | None = "default",
        api_key: str | None = None,
        timeout: float = 15.0,
    ):
        raw_url = (base_url or "").rstrip("/")
        self.session = session or "default"
        self.api_key = api_key or ""
        self.timeout = timeout
        self._candidate_urls = self._build_candidate_urls(raw_url)
        self.base_url = self._candidate_urls[0] if self._candidate_urls else raw_url

    @staticmethod
    def _build_candidate_urls(initial_url: str | None) -> list[str]:
        import os

        candidates: list[str] = []
        if initial_url and initial_url.strip():
            candidates.append(initial_url.strip().rstrip("/"))
        env_url = (os.getenv("WAHA_BASE_URL") or "").strip().rstrip("/")
        if env_url and env_url not in candidates:
            candidates.append(env_url)
        for fallback in [
            "http://agenda_waha:3000",
            "http://waha:3000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]:
            if fallback not in candidates:
                candidates.append(fallback)
        return candidates

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    @staticmethod
    def _clean_phone(phone: str) -> str:
        if str(phone).endswith("@lid"):
            return str(phone)
        digits = re.sub(r"\D", "", str(phone))
        return digits

    def _format_chat_id(self, phone: str) -> str:
        raw = str(phone or "").strip()
        if "@" in raw:
            return raw
        clean = self._clean_phone(raw)
        # Identifica se é um LID do WhatsApp (>= 14 dígitos sem DDI 55 padrão)
        if len(clean) >= 14 and not clean.startswith("55"):
            return f"{clean}@lid"
        return f"{clean}@c.us"

    async def _post_json(
        self,
        endpoint: str,
        payload: dict[str, Any],
        client: httpx.AsyncClient | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{endpoint}"
        req_timeout = timeout or self.timeout
        headers = self._headers()

        if client is not None:
            return await client.post(url, json=payload, headers=headers, timeout=req_timeout)

        try:
            async with httpx.AsyncClient(timeout=req_timeout) as direct_client:
                return await direct_client.post(url, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as initial_err:
            for alt_url in self._candidate_urls:
                if alt_url == self.base_url:
                    continue
                try:
                    alt_target = f"{alt_url}{endpoint}"
                    async with httpx.AsyncClient(timeout=req_timeout) as fallback_client:
                        resp = await fallback_client.post(alt_target, json=payload, headers=headers)
                        logger.info("WAHA failover conectado com sucesso para: %s", alt_url)
                        self.base_url = alt_url
                        return resp
                except Exception:
                    continue
            raise initial_err

    async def _get(
        self,
        endpoint: str,
        client: httpx.AsyncClient | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{endpoint}"
        req_timeout = timeout or self.timeout
        headers = self._headers()

        if client is not None:
            return await client.get(url, headers=headers, timeout=req_timeout)

        try:
            async with httpx.AsyncClient(timeout=req_timeout) as direct_client:
                return await direct_client.get(url, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as initial_err:
            for alt_url in self._candidate_urls:
                if alt_url == self.base_url:
                    continue
                try:
                    alt_target = f"{alt_url}{endpoint}"
                    async with httpx.AsyncClient(timeout=req_timeout) as fallback_client:
                        resp = await fallback_client.get(alt_target, headers=headers)
                        logger.info("WAHA failover conectado com sucesso para: %s", alt_url)
                        self.base_url = alt_url
                        return resp
                except Exception:
                    continue
            raise initial_err

    async def send_text(self, phone: str, text: str) -> SendMessageResult:
        if not self.base_url:
            return SendMessageResult(
                success=False,
                provider=self.name,
                error="URL base do WAHA não configurada.",
            )

        chat_id = self._format_chat_id(phone)
        url = f"{self.base_url}/api/sendText"
        payload = {
            "session": self.session,
            "chatId": chat_id,
            "text": text,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                try:
                    response = await client.post(url, json=payload, headers=self._headers())
                except (httpx.ConnectError, httpx.ConnectTimeout) as conn_err:
                    response = None
                    for alt_url in self._candidate_urls:
                        if alt_url == self.base_url:
                            continue
                        try:
                            alt_resp = await client.post(
                                f"{alt_url}/api/sendText",
                                json=payload,
                                headers=self._headers(),
                            )
                            logger.info("Failover de envio WAHA bem-sucedido via %s", alt_url)
                            self.base_url = alt_url
                            response = alt_resp
                            break
                        except Exception:
                            continue
                    if response is None:
                        raise conn_err

                if response.status_code in (200, 201):
                    data = response.json() if response.text else {}
                    msg_id = data.get("id") or data.get("messageId") or ""
                    return SendMessageResult(
                        success=True,
                        message_id=str(msg_id),
                        provider=self.name,
                        raw_response=data,
                    )
                return SendMessageResult(
                    success=False,
                    provider=self.name,
                    error=f"WAHA retornou erro HTTP {response.status_code}: {response.text}",
                )
        except Exception as exc:
            logger.error("Erro ao enviar mensagem via WAHA: %s", exc)
            return SendMessageResult(
                success=False,
                provider=self.name,
                error=str(exc),
            )

    async def send_image(
        self, phone: str, image_url: str, caption: str | None = None
    ) -> SendMessageResult:
        if not self.base_url:
            return SendMessageResult(
                success=False,
                provider=self.name,
                error="URL base do WAHA não configurada.",
            )

        chat_id = self._format_chat_id(phone)
        url = f"{self.base_url}/api/sendImage"
        payload = {
            "session": self.session,
            "chatId": chat_id,
            "file": {"url": image_url},
            "caption": caption or "",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                try:
                    response = await client.post(url, json=payload, headers=self._headers())
                except (httpx.ConnectError, httpx.ConnectTimeout) as conn_err:
                    response = None
                    for alt_url in self._candidate_urls:
                        if alt_url == self.base_url:
                            continue
                        try:
                            alt_resp = await client.post(
                                f"{alt_url}/api/sendImage",
                                json=payload,
                                headers=self._headers(),
                            )
                            logger.info("Failover de imagem WAHA bem-sucedido via %s", alt_url)
                            self.base_url = alt_url
                            response = alt_resp
                            break
                        except Exception:
                            continue
                    if response is None:
                        raise conn_err

                if response.status_code in (200, 201):
                    data = response.json() if response.text else {}
                    return SendMessageResult(
                        success=True,
                        message_id=str(data.get("id") or ""),
                        provider=self.name,
                        raw_response=data,
                    )
                return SendMessageResult(
                    success=False,
                    provider=self.name,
                    error=f"WAHA retornou erro HTTP {response.status_code}: {response.text}",
                )
        except Exception as exc:
            logger.error("Erro ao enviar imagem via WAHA: %s", exc)
            return SendMessageResult(
                success=False,
                provider=self.name,
                error=str(exc),
            )

    @staticmethod
    def _default_webhook_config() -> dict[str, Any]:
        import os

        webhook_url = (
            os.getenv("WAHA_WEBHOOK_URL")
            or "http://vendedor-ia:8000/api/webhooks/whatsapp/waha"
        )
        return {
            "webhooks": [
                {
                    "url": webhook_url,
                    "events": ["message", "message.any"],
                }
            ]
        }

    def parse_inbound_webhook(self, payload: dict[str, Any]) -> InboundMessage | None:
        """Processa webhook do WAHA (evento 'message', 'message.any' ou 'message.create')."""
        event = payload.get("event")
        msg_data = payload.get("payload") or payload

        if event and event not in ("message", "message.any", "message.create"):
            return None

        is_from_me = bool(msg_data.get("fromMe", False))
        data_block = msg_data.get("_data") or {}
        key_block = data_block.get("key") or msg_data.get("key") or {}

        if is_from_me:
            # Em mensagens enviadas pelo app móvel/bot, o destinatário é o cliente
            target = (
                msg_data.get("to")
                or msg_data.get("chatId")
                or msg_data.get("from")
                or key_block.get("remoteJid")
                or ""
            )
        else:
            # 1. Prioriza identificador canônico de telefone se disponível (remoteJidAlt / participantAlt / senderPn)
            candidate_pns = [
                key_block.get("remoteJidAlt"),
                key_block.get("participantAlt"),
                data_block.get("senderPn"),
                data_block.get("pn"),
                msg_data.get("senderPn"),
                msg_data.get("pn"),
            ]
            canonical = None
            for cand in candidate_pns:
                if cand and ("@c.us" in str(cand) or "@s.whatsapp.net" in str(cand)):
                    canonical = str(cand)
                    break

            target = (
                canonical
                or msg_data.get("from")
                or msg_data.get("chatId")
                or data_block.get("from")
                or key_block.get("remoteJid")
                or ""
            )

        # Ignora mensagens de grupos do WhatsApp
        if str(target).endswith("@g.us"):
            return None

        # Se for um LID (@lid), preserva a tag para roteamento e envio correto
        if str(target).endswith("@lid"):
            clean_digits = re.sub(r"\D", "", str(target))
            clean_phone = f"{clean_digits}@lid"
        else:
            clean_phone = self._clean_phone(target)

        if not clean_phone:
            return None

        text = msg_data.get("body") or msg_data.get("text") or ""
        if not text and isinstance(msg_data.get("caption"), str):
            text = msg_data["caption"]

        if not text and (msg_data.get("selectedRowId") or msg_data.get("selectedButtonId")):
            text = str(msg_data.get("selectedRowId") or msg_data.get("selectedButtonId"))

        text = text.strip()

        media_type = "text"
        media_url = None
        has_media = msg_data.get("hasMedia") is True
        media_info = msg_data.get("media") or {}
        if has_media:
            mimetype = media_info.get("mimetype") or msg_data.get("_data", {}).get("mimetype") or ""
            if "audio" in mimetype or msg_data.get("type") in ("ptt", "audio"):
                media_type = "audio"
                media_url = media_info.get("url")
                if not text:
                    text = "[Mensagem de áudio recebida]"

        if not text and not has_media:
            return None

        msg_id = str(msg_data.get("id") or "")
        data_block = msg_data.get("_data") or {}
        sender_name = (
            "Atendente"
            if is_from_me
            else (
                data_block.get("notifyName")
                or msg_data.get("notifyName")
                or "Cliente"
            )
        )

        return InboundMessage(
            provider=self.name,
            sender_phone=clean_phone,
            sender_name=sender_name,
            text=text,
            message_id=msg_id,
            media_type=media_type,
            media_url=media_url,
            is_from_me=is_from_me,
            raw_payload=payload,
        )

    async def ensure_session_webhook(self, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
        """Garante que a sessão ativa no WAHA está configurada com o webhook do Vendedor IA.

        Se não estiver configurada ou estiver divergente, atualiza via PUT /api/sessions/{session}
        em tempo real sem desconectar a sessão.
        """
        if not self.base_url:
            return {"configured": False, "error": "URL base do WAHA não configurada."}

        target_config = self._default_webhook_config()
        target_url = target_config["webhooks"][0]["url"]

        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            close_client = True

        try:
            get_res = await client.get(
                f"{self.base_url}/api/sessions/{self.session}",
                headers=self._headers(),
            )
            if get_res.status_code != 200:
                return {
                    "configured": False,
                    "error": f"Sessão '{self.session}' não encontrada no WAHA (HTTP {get_res.status_code})",
                }

            session_data = get_res.json()
            config = session_data.get("config") or {}
            webhooks = config.get("webhooks") or []

            already_synced = any(
                isinstance(w, dict) and (w.get("url") == target_url or target_url in str(w.get("url", "")))
                for w in webhooks
            )

            if already_synced:
                return {
                    "configured": True,
                    "already_synced": True,
                    "webhook_url": target_url,
                    "session": self.session,
                }

            logger.info(
                "Sincronizando webhook do Vendedor IA (%s) na sessão WAHA '%s'...",
                target_url,
                self.session,
            )
            put_payload = {
                "name": self.session,
                "config": {
                    **config,
                    "webhooks": target_config["webhooks"],
                },
            }
            put_res = await client.put(
                f"{self.base_url}/api/sessions/{self.session}",
                json=put_payload,
                headers=self._headers(),
            )
            if put_res.status_code in (200, 201):
                logger.info("Webhook WAHA sincronizado com sucesso para '%s'!", target_url)
                return {
                    "configured": True,
                    "synced": True,
                    "webhook_url": target_url,
                    "session": self.session,
                }

            return {
                "configured": False,
                "error": f"WAHA recusou configuração de webhook: HTTP {put_res.status_code} - {put_res.text}",
            }
        except Exception as exc:
            logger.warning("Falha ao validar/sincronizar webhook no WAHA: %s", exc)
            return {"configured": False, "error": str(exc)}
        finally:
            if close_client:
                await client.aclose()

    async def check_health(self) -> dict[str, Any]:
        if not self.base_url:
            return {"configured": False, "status": "not_configured"}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(
                    f"{self.base_url}/api/sessions/{self.session}",
                    headers=self._headers(),
                )
                if res.status_code == 200:
                    data = res.json()
                    status = data.get("status") or "online"
                    if status in ("WORKING", "online", "PAIRED"):
                        try:
                            await self.ensure_session_webhook(client=client)
                        except Exception as sync_err:
                            logger.debug("Falha ao checar webhook no check_health: %s", sync_err)
                    return {"configured": True, "status": status, "session": self.session, "base_url": self.base_url}
                return {
                    "configured": True,
                    "status": "error",
                    "http_code": res.status_code,
                    "base_url": self.base_url,
                }
        except Exception as exc:
            return {"configured": True, "status": "unavailable", "detail": str(exc), "base_url": self.base_url}

    async def get_qr_status(self) -> dict[str, Any]:
        """Consulta status da sessão e retorna o QR Code em Base64 se aguardando pareamento."""
        if not self.base_url:
            return {"success": False, "error": "URL base do WAHA não configurada."}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    f"{self.base_url}/api/sessions/{self.session}",
                    headers=self._headers(),
                )

                if res.status_code == 404:
                    # Sessão não existe, cria e inicializa com webhook do Vendedor IA
                    await client.post(
                        f"{self.base_url}/api/sessions/",
                        json={
                            "name": self.session,
                            "config": self._default_webhook_config(),
                        },
                        headers=self._headers(),
                    )
                    await client.post(
                        f"{self.base_url}/api/sessions/{self.session}/start",
                        headers=self._headers(),
                    )
                    await asyncio.sleep(1.5)
                    res = await client.get(
                        f"{self.base_url}/api/sessions/{self.session}",
                        headers=self._headers(),
                    )

                if res.status_code != 200:
                    return {"success": False, "error": f"Erro do WAHA HTTP {res.status_code}"}

                data = res.json()
                status = data.get("status") or "UNKNOWN"
                me = data.get("me")

                if status in ("STOPPED", "FAILED"):
                    try:
                        await client.post(
                            f"{self.base_url}/api/sessions/{self.session}/stop",
                            headers=self._headers(),
                            timeout=5.0,
                        )
                    except Exception as stop_exc:
                        logger.debug("Tentativa de parar sessão WAHA ignorada: %s", stop_exc)

                    await client.post(
                        f"{self.base_url}/api/sessions/{self.session}/start",
                        headers=self._headers(),
                        timeout=5.0,
                    )
                    await asyncio.sleep(2.0)
                    res = await client.get(
                        f"{self.base_url}/api/sessions/{self.session}",
                        headers=self._headers(),
                    )
                    if res.status_code == 200:
                        data = res.json()
                        status = data.get("status") or "UNKNOWN"
                        me = data.get("me")

                # Se a sessão estiver ativa, garante que o webhook está sincronizado
                if status in ("WORKING", "PAIRED"):
                    try:
                        await self.ensure_session_webhook(client=client)
                    except Exception as sync_err:
                        logger.debug("Falha na sincronização de webhook durante get_qr_status: %s", sync_err)

                qr_code = None
                if status == "SCAN_QR_CODE":
                    try:
                        qr_res = await client.get(
                            f"{self.base_url}/api/{self.session}/auth/qr",
                            headers=self._headers(),
                            timeout=5.0,
                        )
                        if qr_res.status_code == 200 and qr_res.content:
                            b64 = base64.b64encode(qr_res.content).decode("ascii")
                            qr_code = f"data:image/png;base64,{b64}"
                    except Exception as qr_err:
                        logger.warning("Falha ao obter imagem do QR Code: %s", qr_err)

                return {
                    "success": True,
                    "status": status,
                    "me": me,
                    "qr_code": qr_code,
                }
        except Exception as exc:
            logger.error("Erro ao consultar QR status do WAHA: %s", exc)
            return {"success": False, "error": str(exc)}

    async def restart_session(self) -> dict[str, Any]:
        """Reinicia a sessão no WAHA para forçar novo QR Code."""
        if not self.base_url:
            return {"success": False, "error": "URL base do WAHA não configurada."}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    await client.post(
                        f"{self.base_url}/api/sessions/{self.session}/stop",
                        headers=self._headers(),
                        timeout=5.0,
                    )
                except Exception as stop_exc:
                    logger.debug("Tentativa de parar sessão WAHA antes do restart ignorada: %s", stop_exc)

                res = await client.post(
                    f"{self.base_url}/api/sessions/{self.session}/start",
                    json={"config": self._default_webhook_config()},
                    headers=self._headers(),
                    timeout=5.0,
                )
                return {"success": res.status_code in (200, 201)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def logout_session(self) -> dict[str, Any]:
        """Desconecta a conta do WhatsApp no WAHA."""
        if not self.base_url:
            return {"success": False, "error": "URL base do WAHA não configurada."}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/sessions/{self.session}/logout",
                    headers=self._headers(),
                )
                return {"success": res.status_code in (200, 201, 204)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
