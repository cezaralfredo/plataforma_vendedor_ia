from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.payment import Payment
from app.models.seller import Seller
from app.seller.auth import (
    _SELLER_SESSION_COOKIE,
    get_current_seller,
    make_seller_session_cookie,
    read_seller_session_cookie,
)
from app.services.seller_service import SellerService

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/seller", tags=["Área do Vendedor"])


@router.get("/login", response_class=HTMLResponse)
async def seller_login_page(
    request: Request,
    db: Session = Depends(get_db),
    vendedor_session: Annotated[str | None, Cookie()] = None,
):
    seller_id = read_seller_session_cookie(vendedor_session)
    if seller_id:
        seller = db.query(Seller).filter(Seller.id == seller_id, Seller.active.is_(True)).first()
        if seller:
            return RedirectResponse(url="/seller/dashboard", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def seller_login_action(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    service = SellerService(db)
    seller = service.authenticate(email=email, password=password)

    if not seller:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "E-mail ou senha incorretos."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    cookie_value = make_seller_session_cookie(seller.id)
    redirect = RedirectResponse(url="/seller/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    redirect.set_cookie(
        key=_SELLER_SESSION_COOKIE,
        value=cookie_value,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 7,
    )
    return redirect


@router.post("/logout")
async def seller_logout():
    redirect = RedirectResponse(url="/seller/login", status_code=status.HTTP_303_SEE_OTHER)
    redirect.delete_cookie(_SELLER_SESSION_COOKIE)
    return redirect


@router.get("/dashboard", response_class=HTMLResponse)
async def seller_dashboard(
    request: Request,
    seller: Seller = Depends(get_current_seller),
    db: Session = Depends(get_db),
):
    service = SellerService(db)
    metrics = service.get_metrics(seller.id)

    orders = (
        db.query(Payment)
        .filter(Payment.seller_id == seller.id)
        .order_by(Payment.created_at.desc())
        .limit(20)
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "seller": seller,
            "branch": seller.branch,
            "metrics": metrics,
            "orders": orders,
        },
    )


@router.get("/api/metrics")
async def seller_metrics_api(
    seller: Seller = Depends(get_current_seller),
    db: Session = Depends(get_db),
):
    service = SellerService(db)
    return service.get_metrics(seller.id)
