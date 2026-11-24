import base64
import ipaddress
import logging
import os
import re
import socket
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models.company_settings import CompanySettings
from app.services.company_settings_service import CompanySettingsService

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # 15 MB

TRANSCRIPTION_PROMPT = (
    "Transcreva fielmente este áudio em português do Brasil. "
    "Retorne APENAS o texto falado pelo cliente, sem comentários, sem aspas e sem formatação extra. "
    "Se o áudio estiver completamente inaudível ou vazio, retorne apenas uma string vazia."
)

OPENROUTER_AUDIO_MODELS = (
    "google/gemini-2.5-flash",
    "google/gemini-2.0-flash-001",
)

GEMINI_AUDIO_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}  # noqa: S104


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


def _infer_provider_from_key(api_key: str, configured_provider: str) -> str:
    """Infere o provedor real a partir do prefixo da chave quando há divergência evidente."""
    key = (api_key or "").strip()
    if key.startswith("sk-or-"):
        return "openrouter"
    if key.startswith("gsk_"):
        return "groq"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-ant-"):
        return "anthropic"
    return (configured_provider or "openai").lower().strip()


def _detect_audio_format(
    audio_data: bytes,
    filename: str = "audio.ogg",
    mimetype: str | None = None,
) -> tuple[str, str, str]:
    """Detecta (formato_curto, mime_type_limpo, filename) via magic bytes, MIME e extensão."""
    if audio_data.startswith(b"OggS"):
        return "ogg", "audio/ogg", "audio.ogg"
    if audio_data.startswith(b"RIFF") and audio_data[8:12] == b"WAVE":
        return "wav", "audio/wav", "audio.wav"
    if audio_data.startswith(b"ID3") or (
        len(audio_data) >= 2 and audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0
    ):
        return "mp3", "audio/mpeg", "audio.mp3"
    if len(audio_data) >= 12 and audio_data[4:8] == b"ftyp":
        return "m4a", "audio/mp4", "audio.m4a"
    if audio_data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm", "audio/webm", "audio.webm"
    if audio_data.startswith(b"fLaC"):
        return "flac", "audio/flac", "audio.flac"

    clean_mime = (mimetype or "").split(";", 1)[0].strip().lower()
    mime_map = {
        "audio/ogg": ("ogg", "audio/ogg", "audio.ogg"),
        "audio/opus": ("ogg", "audio/ogg", "audio.ogg"),
        "audio/mpeg": ("mp3", "audio/mpeg", "audio.mp3"),
        "audio/mp3": ("mp3", "audio/mpeg", "audio.mp3"),
        "audio/mp4": ("m4a", "audio/mp4", "audio.m4a"),
        "audio/x-m4a": ("m4a", "audio/mp4", "audio.m4a"),
        "audio/aac": ("aac", "audio/aac", "audio.aac"),
        "audio/wav": ("wav", "audio/wav", "audio.wav"),
        "audio/x-wav": ("wav", "audio/wav", "audio.wav"),
        "audio/webm": ("webm", "audio/webm", "audio.webm"),
        "audio/flac": ("flac", "audio/flac", "audio.flac"),
    }
    if clean_mime in mime_map:
        return mime_map[clean_mime]

    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    ext_map = {
        "ogg": ("ogg", "audio/ogg", "audio.ogg"),
        "oga": ("ogg", "audio/ogg", "audio.ogg"),
        "opus": ("ogg", "audio/ogg", "audio.ogg"),
        "mp3": ("mp3", "audio/mpeg", "audio.mp3"),
        "m4a": ("m4a", "audio/mp4", "audio.m4a"),
        "mp4": ("m4a", "audio/mp4", "audio.m4a"),
        "aac": ("aac", "audio/aac", "audio.aac"),
        "wav": ("wav", "audio/wav", "audio.wav"),
        "webm": ("webm", "audio/webm", "audio.webm"),
        "flac": ("flac", "audio/flac", "audio.flac"),
    }
    return ext_map.get(ext, ("ogg", "audio/ogg", "audio.ogg"))


class AudioTranscriptionService:
    """
    Serviço multi-provedor de transcrição de áudios recebidos pelo WhatsApp.
    Suporta nativamente:
    - OpenRouter (multimodal `input_audio` via Gemini Flash, sem precisar de chave OpenAI extra)
    - Google Gemini (API nativa `generateContent` com `inline_data`)
    - Groq (Whisper `whisper-large-v3-turbo`)
    - OpenAI (Whisper `whisper-1`)
    - Custom OpenAI-compatible (`/audio/transcriptions`)
    Com cascata automática de fallback entre quaisquer chaves configuradas no sistema.
    """

    def __init__(self, db: Session):
        self.db = db
        self.company_settings: CompanySettings = CompanySettingsService(db).get_or_create_default()

    def _effective_waha_base_url(self) -> str:
        return (
            (self.company_settings.waha_base_url or "").strip()
            or (os.getenv("WAHA_BASE_URL") or "").strip()
            or "http://waha:3000"
        ).rstrip("/")

    def _effective_evolution_base_url(self) -> str:
        return (
            (self.company_settings.evolution_base_url or "").strip()
            or (os.getenv("EVOLUTION_BASE_URL") or "").strip()
        ).rstrip("/")

    def _allowed_internal_hosts(self) -> set[str]:
        hosts: set[str] = {"waha", "agenda_waha"}
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

    def _normalize_media_url(self, audio_url: str, provider: str | None = None) -> str:
        """Reescreve URLs loopback (ex: localhost:3000 do WAHA) para o host interno do container."""
        url = (audio_url or "").strip()
        if not url or url.startswith("meta-media://"):
            return url

        try:
            parsed = urlparse(url)
        except ValueError:
            return url

        hostname = (parsed.hostname or "").lower()
        if hostname not in _LOCAL_HOSTS:
            return url

        prov = (provider or self.company_settings.whatsapp_provider or "").lower().strip()
        replacement_base = ""
        if prov == "waha":
            replacement_base = self._effective_waha_base_url()
        elif prov == "evolution":
            replacement_base = self._effective_evolution_base_url()

        if not replacement_base:
            return url

        target_parsed = urlparse(replacement_base)
        if not target_parsed.scheme or not target_parsed.netloc:
            return url

        rewritten = urlunparse(
            (
                target_parsed.scheme,
                target_parsed.netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                "",
            )
        )
        logger.debug("URL de mídia loopback reescrita (%s): %s -> %s", prov, url, rewritten)
        return rewritten

    def _build_provider_auth_headers(
        self, audio_url: str, provider: str | None = None
    ) -> dict[str, str]:
        """Monta headers de autenticação apenas para hosts internos confiáveis do provedor."""
        try:
            hostname = (urlparse(audio_url).hostname or "").lower()
        except ValueError:
            return {}

        if hostname not in self._allowed_internal_hosts():
            return {}

        prov = (provider or self.company_settings.whatsapp_provider or "").lower().strip()
        if prov == "waha":
            waha_key = (
                (self.company_settings.waha_api_key or "").strip()
                or (os.getenv("WAHA_API_KEY") or "").strip()
            )
            if waha_key:
                return {"X-Api-Key": waha_key}
        elif prov == "evolution":
            evo_key = (
                (self.company_settings.evolution_api_key or "").strip()
                or (os.getenv("EVOLUTION_API_KEY") or "").strip()
            )
            if evo_key:
                return {"apikey": evo_key}
        return {}

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

    def _resolve_transcription_candidates(self) -> list[tuple[str, str, str]]:
        """
        Retorna lista ordenada e deduplicada de (provider, api_key, base_url)
        capazes de transcrever áudio, priorizando o provedor ativo e fazendo fallback
        automático para qualquer outra chave configurada (OpenRouter, Gemini, Groq, OpenAI).
        """
        candidates: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()

        def _add(provider: str, api_key: str | None, base_url: str = "") -> None:
            prov = (provider or "").lower().strip()
            key = (api_key or "").strip()
            if prov == "anthropic":
                return  # Claude não aceita entrada de áudio nativamente
            if prov != "custom" and not key:
                return
            if prov == "custom" and not base_url:
                return
            dedup_key = (prov, key or base_url)
            if dedup_key not in seen:
                seen.add(dedup_key)
                candidates.append((prov, key, base_url.rstrip("/")))

        custom_cfg = self.company_settings.custom_settings or {}
        if isinstance(custom_cfg, dict):
            override_prov = str(custom_cfg.get("audio_transcription_provider") or "").strip().lower()
            override_key = str(custom_cfg.get("audio_transcription_api_key") or "").strip()
            override_base = str(custom_cfg.get("audio_transcription_base_url") or "").strip()
            if override_prov and override_key:
                _add(override_prov, override_key, override_base)

        env_keys: dict[str, str] = {
            "groq": (app_settings.groq_api_key or os.getenv("GROQ_API_KEY") or "").strip(),
            "openai": (app_settings.openai_api_key or os.getenv("OPENAI_API_KEY") or "").strip(),
            "gemini": (app_settings.gemini_api_key or os.getenv("GEMINI_API_KEY") or "").strip(),
            "openrouter": (app_settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY") or "").strip(),
        }

        primary_provider = (self.company_settings.ai_provider or "openai").lower().strip()
        primary_key = (self.company_settings.ai_api_key or "").strip()
        primary_base = (self.company_settings.ai_base_url or "").strip()

        if primary_key:
            inferred_provider = _infer_provider_from_key(primary_key, primary_provider)
            _add(inferred_provider, primary_key, primary_base if inferred_provider in {"openrouter", "custom"} else "")
        elif env_keys.get(primary_provider):
            _add(primary_provider, env_keys[primary_provider], primary_base if primary_provider == "openrouter" else "")
        elif primary_provider == "custom" and primary_base:
            _add("custom", "local-key", primary_base)

        # Cascata automática de fallback com todas as demais chaves disponíveis no ambiente
        for fallback_provider in ("groq", "openai", "gemini", "openrouter"):
            _add(fallback_provider, env_keys.get(fallback_provider))

        return candidates

    async def _transcribe_whisper_compatible(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        audio_data: bytes,
        filename: str,
        mime_type: str,
        provider_label: str,
    ) -> str | None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        files = {"file": (filename, audio_data, mime_type)}
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
                    if transcription:
                        logger.info("Áudio transcrito com sucesso via %s (%s).", provider_label, model)
                        return transcription
                    return None
                logger.warning(
                    "Falha na transcrição Whisper (%s): HTTP %s - %s",
                    provider_label,
                    res.status_code,
                    res.text[:300],
                )
        except Exception as exc:
            logger.error("Erro na transcrição Whisper (%s): %s", provider_label, exc)
        return None

    async def _transcribe_via_openrouter(
        self,
        api_key: str,
        base_url: str,
        audio_data: bytes,
        audio_format: str,
    ) -> str | None:
        endpoint = f"{(base_url or 'https://openrouter.ai/api/v1').rstrip('/')}/chat/completions"
        encoded_audio = base64.b64encode(audio_data).decode("ascii")

        custom_cfg = self.company_settings.custom_settings or {}
        custom_model = (
            str(custom_cfg.get("audio_transcription_model") or "").strip()
            if isinstance(custom_cfg, dict)
            else ""
        )
        models_to_try = [custom_model, *OPENROUTER_AUDIO_MODELS] if custom_model else list(OPENROUTER_AUDIO_MODELS)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://vende360.local",
            "X-Title": "Plataforma Vendedor IA",
        }

        async with httpx.AsyncClient(timeout=40.0) as client:
            for model in models_to_try:
                payload = {
                    "model": model,
                    "temperature": 0.0,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": TRANSCRIPTION_PROMPT},
                                {
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": encoded_audio,
                                        "format": audio_format,
                                    },
                                },
                            ],
                        }
                    ],
                }
                try:
                    res = await client.post(endpoint, headers=headers, json=payload)
                    if res.status_code != 200:
                        logger.warning(
                            "Falha na transcrição via OpenRouter (%s): HTTP %s - %s",
                            model,
                            res.status_code,
                            res.text[:300],
                        )
                        continue
                    data = res.json()
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    content = (choices[0].get("message") or {}).get("content")
                    if isinstance(content, list):
                        text = " ".join(
                            str(part.get("text") or "")
                            for part in content
                            if isinstance(part, dict)
                        ).strip()
                    else:
                        text = str(content or "").strip()
                    if text:
                        logger.info("Áudio transcrito com sucesso via OpenRouter (%s).", model)
                        return text
                except Exception as exc:
                    logger.error("Erro na transcrição via OpenRouter (%s): %s", model, exc)
        return None

    async def _transcribe_via_gemini(
        self,
        api_key: str,
        audio_data: bytes,
        mime_type: str,
    ) -> str | None:
        encoded_audio = base64.b64encode(audio_data).decode("ascii")
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": TRANSCRIPTION_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": encoded_audio,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.0},
        }

        async with httpx.AsyncClient(timeout=40.0) as client:
            for model in GEMINI_AUDIO_MODELS:
                endpoint = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                )
                try:
                    res = await client.post(endpoint, headers=headers, json=payload)
                    if res.status_code != 200:
                        logger.warning(
                            "Falha na transcrição via Gemini (%s): HTTP %s - %s",
                            model,
                            res.status_code,
                            res.text[:300],
                        )
                        continue
                    data = res.json()
                    candidates = data.get("candidates") or []
                    if not candidates:
                        continue
                    parts = (candidates[0].get("content") or {}).get("parts") or []
                    text = " ".join(
                        str(part.get("text") or "")
                        for part in parts
                        if isinstance(part, dict)
                    ).strip()
                    if text:
                        logger.info("Áudio transcrito com sucesso via Gemini (%s).", model)
                        return text
                except Exception as exc:
                    logger.error("Erro na transcrição via Gemini (%s): %s", model, exc)
        return None

    async def transcribe_audio_bytes(
        self,
        audio_data: bytes,
        filename: str = "audio.ogg",
        mimetype: str | None = None,
    ) -> str | None:
        """Transcreve bytes de áudio usando o provedor ativo ou cascata de fallback multi-provedor."""
        if not audio_data or len(audio_data) < 100:
            return None
        if len(audio_data) > MAX_AUDIO_BYTES:
            logger.warning("Áudio excedeu o limite máximo de %d bytes.", MAX_AUDIO_BYTES)
            return None

        candidates = self._resolve_transcription_candidates()
        if not candidates:
            logger.warning(
                "Transcrição de áudio indisponível: nenhuma chave compatível configurada "
                "(OpenRouter, Gemini, Groq ou OpenAI)."
            )
            return None

        audio_format, clean_mime, clean_filename = _detect_audio_format(
            audio_data, filename=filename, mimetype=mimetype
        )

        for provider, api_key, base_url in candidates:
            result: str | None = None
            if provider == "groq":
                result = await self._transcribe_whisper_compatible(
                    endpoint="https://api.groq.com/openai/v1/audio/transcriptions",
                    api_key=api_key,
                    model="whisper-large-v3-turbo",
                    audio_data=audio_data,
                    filename=clean_filename,
                    mime_type=clean_mime,
                    provider_label="groq",
                )
            elif provider == "openai":
                result = await self._transcribe_whisper_compatible(
                    endpoint="https://api.openai.com/v1/audio/transcriptions",
                    api_key=api_key,
                    model="whisper-1",
                    audio_data=audio_data,
                    filename=clean_filename,
                    mime_type=clean_mime,
                    provider_label="openai",
                )
            elif provider == "openrouter":
                result = await self._transcribe_via_openrouter(
                    api_key=api_key,
                    base_url=base_url or "https://openrouter.ai/api/v1",
                    audio_data=audio_data,
                    audio_format=audio_format,
                )
            elif provider == "gemini":
                result = await self._transcribe_via_gemini(
                    api_key=api_key,
                    audio_data=audio_data,
                    mime_type=clean_mime,
                )
            elif provider == "custom" and base_url:
                result = await self._transcribe_whisper_compatible(
                    endpoint=f"{base_url}/audio/transcriptions",
                    api_key=api_key,
                    model="whisper-1",
                    audio_data=audio_data,
                    filename=clean_filename,
                    mime_type=clean_mime,
                    provider_label="custom",
                )

            if result:
                return result

        logger.warning(
            "Todas as tentativas de transcrição falharam (provedores tentados: %s).",
            [c[0] for c in candidates],
        )
        return None

    async def transcribe_base64(
        self, encoded_audio: str, mimetype: str | None = None
    ) -> str | None:
        """Decodifica áudio recebido em base64 (WAHA/Evolution) e executa transcrição."""
        raw = (encoded_audio or "").strip()
        if not raw:
            return None
        detected_mime = mimetype
        if raw.startswith("data:") and "," in raw:
            header, raw = raw.split(",", 1)
            if not detected_mime and ";" in header:
                detected_mime = header[5:].split(";", 1)[0].strip()
        try:
            audio_bytes = base64.b64decode(raw, validate=False)
        except Exception as exc:
            logger.warning("Falha ao decodificar áudio base64: %s", exc)
            return None
        return await self.transcribe_audio_bytes(audio_bytes, mimetype=detected_mime)

    async def _download_meta_media(self, media_id: str) -> tuple[bytes | None, str | None]:
        """Resolve e baixa mídia de áudio autenticada da Meta Graph API."""
        clean_id = re.sub(r"[^A-Za-z0-9_-]", "", media_id or "")
        if not clean_id:
            return None, None

        token = (
            (self.company_settings.meta_access_token or "").strip()
            or (os.getenv("META_ACCESS_TOKEN") or "").strip()
        )
        if not token:
            logger.warning("META_ACCESS_TOKEN ausente para download de áudio Meta (media_id=%s).", clean_id)
            return None, None

        headers = {"Authorization": f"Bearer {token}"}
        meta_info_url = f"https://graph.facebook.com/v20.0/{clean_id}"
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                meta_res = await client.get(meta_info_url, headers=headers)
                if meta_res.status_code != 200:
                    logger.warning("Falha ao consultar metadados de mídia Meta: HTTP %s", meta_res.status_code)
                    return None, None
                info = meta_res.json()
                download_url = str(info.get("url") or "").strip()
                mime_type = str(info.get("mime_type") or "").strip() or None
                if not download_url or not self._is_safe_audio_url(download_url):
                    logger.warning("URL de download da mídia Meta rejeitada pela validação SSRF.")
                    return None, None
                async with client.stream("GET", download_url, headers=headers) as res:
                    if res.status_code != 200:
                        logger.warning("Falha ao baixar mídia Meta: HTTP %s", res.status_code)
                        return None, None
                    chunks = bytearray()
                    async for chunk in res.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > MAX_AUDIO_BYTES:
                            logger.warning("Áudio Meta excedeu o limite máximo de %d bytes.", MAX_AUDIO_BYTES)
                            return None, None
                    return bytes(chunks), mime_type
        except Exception as exc:
            logger.error("Erro ao baixar mídia de áudio da Meta (%s): %s", clean_id, exc)
            return None, None

    async def download_and_transcribe(
        self,
        audio_url: str,
        auth_header: dict[str, str] | None = None,
        provider: str | None = None,
        mimetype: str | None = None,
    ) -> str | None:
        """Baixa o arquivo de áudio (com rewrite WAHA/Evolution, auth e SSRF) e executa a transcrição."""
        raw_url = (audio_url or "").strip()
        if not raw_url:
            return None

        if raw_url.startswith("meta-media://"):
            media_id = raw_url.removeprefix("meta-media://")
            audio_bytes, meta_mime = await self._download_meta_media(media_id)
            if audio_bytes:
                return await self.transcribe_audio_bytes(
                    audio_bytes, mimetype=mimetype or meta_mime
                )
            return None

        normalized_url = self._normalize_media_url(raw_url, provider=provider)
        if not self._is_safe_audio_url(normalized_url):
            logger.warning("Download de áudio bloqueado por validação SSRF: %s", normalized_url)
            return None

        headers = self._build_provider_auth_headers(normalized_url, provider=provider)
        if auth_header:
            headers.update(auth_header)

        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
                async with client.stream("GET", normalized_url, headers=headers) as res:
                    if res.status_code != 200:
                        logger.warning(
                            "Falha ao baixar áudio (%s): HTTP %s",
                            normalized_url,
                            res.status_code,
                        )
                        return None
                    resp_mime = res.headers.get("content-type") or mimetype
                    chunks = bytearray()
                    async for chunk in res.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > MAX_AUDIO_BYTES:
                            logger.warning(
                                "Áudio excedeu o limite máximo de %d bytes: %s",
                                MAX_AUDIO_BYTES,
                                normalized_url,
                            )
                            return None
                    if chunks:
                        return await self.transcribe_audio_bytes(
                            bytes(chunks),
                            filename=os.path.basename(urlparse(normalized_url).path) or "audio.ogg",
                            mimetype=resp_mime,
                        )
        except Exception as exc:
            logger.error("Erro ao baixar áudio do WhatsApp (%s): %s", normalized_url, exc)
        return None
