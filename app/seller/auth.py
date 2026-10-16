import base64
import hashlib
import hmac
import json
import time
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.seller import Seller

_SELLER_SESSION_COOKIE = "vendedor_session"
_SELLER_SESSION_TTL = 60 * 60 * 24 * 7  # 7 dias


def _seller_secret() -> bytes:
    key = settings.admin_api_key or settings.api_key or "default-secret"
    return hashlib.sha256(f"seller_session_secret_{key}".encode()).digest()


def make_seller_session_cookie(seller_id: int) -> str:
    payload_dict = {
        "sub": seller_id,
        "exp": int(time.time()) + _SELLER_SESSION_TTL,
    }
    payload_bytes = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
    sig = hmac.new(_seller_secret(), payload_bytes, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")
    return f"{payload_b64}.{sig_b64}"


def read_seller_session_cookie(cookie_value: str | None) -> int | None:
    if not cookie_value or "." not in cookie_value:
        return None
    try:
        payload_b64, sig_b64 = cookie_value.split(".", 1)
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        sig = base64.urlsafe_b64decode(sig_b64.encode("ascii"))
        expected = hmac.new(_seller_secret(), payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload_bytes.decode("utf-8"))
        if data.get("exp", 0) < time.time():
            return None
        return int(data["sub"])
    except Exception:
        return None


def get_current_seller(
    request: Request,
    db: Session = Depends(get_db),
    vendedor_session: Annotated[str | None, Cookie()] = None,
) -> Seller:
    seller_id = read_seller_session_cookie(vendedor_session)
    if not seller_id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/seller/login"},
        )

    seller = db.query(Seller).filter(Seller.id == seller_id, Seller.active.is_(True)).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/seller/login"},
        )

    return seller
