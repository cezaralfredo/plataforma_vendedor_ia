import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.models.company_settings import CompanySettings
from app.services.company_settings_service import CompanySettingsService

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # 15 MB


def _is_ip_blocked(ip_str: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


class AudioTranscriptionService:
    """
    Serviço de transcrição de áudios recebidos pelo WhatsApp usando Whisper
    (compatível com OpenAI e Groq - ultra rápido).
    """

    def __init__(self, db: Session):
        self.db = db
        self.company_settings: CompanySettings = CompanySettingsService(db).get_or_create_default()

    def _allowed_internal_hosts(self) -> set[str]:
        hosts: set[str] = set()
        for raw_url in (
            self.company_settings.waha_base_url,
            self.company_settings.evolution_base_url,
            os.getenv("WAHA_BASE_URL"),
            os.getenv("EVOLUTION_BASE_URL"),
        ):
            if raw_url:
                parsed = urlparse(raw_url.strip())
                if parsed.hostname:
                    hosts.add(parsed.hostname.lower())
        return hosts

    def _is_safe_audio_url(self, audio_url: str) -> bool:
        try:
            parsed = urlparse(audio_url.strip())
        except ValueError:
            return False

        scheme = (parsed.scheme or "").lower()
        hostname = (parsed.hostname or "").lower()
        if scheme not in {"http", "https"} or not hostname:
            return False

        # Permite explicitamente o host configurado do WAHA/Evolution (ex: http://waha:3000)
        if hostname in self._allowed_internal_hosts():
            return True

        # Para qualquer outro destino externo, exige HTTPS e bloqueia IPs privados/metadata
        if scheme != "https":
            return False

        try:
            addr_infos = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except OSError:
            return False

        if not addr_infos:
            return False
        for info in addr_infos:
            ip_addr = str(info[4][0])
            if _is_ip_blocked(ip_addr):
                return False
        return True

    async def transcribe_audio_bytes(self, audio_data: bytes, filename: str = "audio.ogg") -> str | None:
        """Transcreve arquivo de áudio usando OpenAI ou Groq Whisper."""
        if not audio_data or len(audio_data) < 100:
            return None

        api_key = self.company_settings.ai_api_key
        if not api_key:
            logger.info("Transcrição de áudio ignorada: nenhuma chave de IA configurada.")
            return None

        provider = (self.company_settings.ai_provider or "openai").lower()

        if provider == "groq":
            endpoint = "https://api.groq.com/openai/v1/audio/transcriptions"
            model = "whisper-large-v3-turbo"
        else:
            endpoint = "https://api.openai.com/v1/audio/transcriptions"
            model = "whisper-1"

        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        files = {
            "file": (filename, audio_data, "audio/ogg"),
        }
        data = {
            "model": model,
            "language": "pt",
            "temperature": "0.0",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(endpoint, headers=headers, files=files, data=data)
                if res.status_code == 200:
                    result = res.json()
                    transcription = (result.get("text") or "").strip()
                    logger.info("Áudio transcrito com sucesso via %s: '%s'", provider, transcription)
                    return transcription
                else:
                    logger.warning("Falha na API Whisper (%s): HTTP %s - %s", provider, res.status_code, res.text)
                    return None
        except Exception as exc:
            logger.error("Erro ao chamar serviço de transcrição Whisper: %s", exc)
            return None

    async def download_and_transcribe(self, audio_url: str, auth_header: dict[str, str] | None = None) -> str | None:
        """Baixa o arquivo de áudio da URL (com proteção SSRF e limite de bytes) e executa a transcrição."""
        if not self._is_safe_audio_url(audio_url):
            logger.warning("Download de áudio bloqueado por validação SSRF: %s", audio_url)
            return None

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                async with client.stream("GET", audio_url, headers=auth_header or {}) as res:
                    if res.status_code != 200:
                        logger.warning("Falha ao baixar áudio (%s): HTTP %s", audio_url, res.status_code)
                        return None
                    chunks = bytearray()
                    async for chunk in res.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > MAX_AUDIO_BYTES:
                            logger.warning("Áudio excedeu o limite máximo de %d bytes: %s", MAX_AUDIO_BYTES, audio_url)
                            return None
                    if chunks:
                        return await self.transcribe_audio_bytes(bytes(chunks))
        except Exception as exc:
            logger.error("Erro ao baixar áudio do WhatsApp (%s): %s", audio_url, exc)
        return None
