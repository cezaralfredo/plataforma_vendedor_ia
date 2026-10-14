"""Autenticação do painel administrativo — login real com sessão (cookie assinado).

Usa apenas a stdlib:
- Hash de senha: hashlib.pbkdf2_hmac (PBKDF2-HMAC-SHA256) + salt aleatório.
- Sessão: cookie assinado com HMAC-SHA256 usando um segredo derivado da
  ADMIN_API_KEY (não é possível forjar payload sem conhecer o segredo).

Formato do cookie: <b64url(payload)>.<b64url(hmac_sha256(payload))>
Payload: {"sub": <admin_user_id>, "exp": <unix_ts>}
"""

import base64
import hashlib
import hmac
import json
import os
import time

from app.config import settings

_SESSION_COOKIE = "atende_admin_session"
_SESSION_TTL = 60 * 60 * 12  # 12 horas
_PBKDF2_ROUNDS = 100_000


# ---------------------------------------------------------------------------
# Hash de senha (PBKDF2-HMAC-SHA256)
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS
    )
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ROUNDS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(dk).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds_s, salt_b64, dk_b64 = stored.split("$", 3)
        rounds = int(rounds_s)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(dk_b64.encode("ascii"))
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, rounds
    )
    return hmac.compare_digest(dk, expected)


# ---------------------------------------------------------------------------
# Sessão (cookie assinado)
# ---------------------------------------------------------------------------
def _secret() -> bytes:
    # Segredo derivado da ADMIN_API_KEY — no navegador o usuário nunca vê a
    # chave e não consegue forjar o cookie sem possuí-la.
    return hashlib.sha256(settings.admin_api_key.encode("utf-8")).digest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def issue_session(admin_user_id: int) -> str:
    """Gera o valor do cookie de sessão para um admin."""
    payload = json.dumps({"sub": int(admin_user_id), "exp": int(time.time()) + _SESSION_TTL})
    payload_b = payload.encode("utf-8")
    sig = hmac.new(_secret(), payload_b, hashlib.sha256).digest()
    return f"{_b64url(payload_b)}.{_b64url(sig)}"


def read_session(cookie_value: str | None) -> int | None:
    """Valida o cookie e retorna o admin_user_id, ou None se inválido/expirado."""
    if not cookie_value:
        return None
    try:
        payload_b64, sig_b64 = cookie_value.split(".", 1)
        payload_b = _b64url_decode(payload_b64)
        sig = _b64url_decode(sig_b64)
    except Exception:
        return None
    expected = hmac.new(_secret(), payload_b, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(payload_b.decode("utf-8"))
    except Exception:
        return None
    if int(data.get("exp", 0)) < time.time():
        return None
    sub = data.get("sub")
    return int(sub) if isinstance(sub, (int, float, str)) else None


def session_cookie_name() -> str:
    return _SESSION_COOKIE


def session_ttl() -> int:
    return _SESSION_TTL