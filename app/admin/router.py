import hmac
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin.auth_service import authenticate_admin, change_admin_password, verify_password
from app.admin.schemas import (
    AdminAppointmentCreate,
    AdminAppointmentUpdate,
    AdminClientCreate,
    AdminClientPage,
    AdminClientSummary,
    AdminClientUpdate,
    AdminMaintenancePreview,
    AdminMaintenancePurgeRequest,
    AdminMaintenancePurgeResult,
    AdminPaymentsResponse,
    AdminSystemStatus,
    AppointmentAction,
    PaymentAction,
    PaymentActionResult,
)
from app.admin.service import AdminService
from app.database import get_db
from app.models.admin_account import AdminAccount
from app.models.payment import Payment
from app.models.user import User
from app.schemas.branch import BranchCreate, BranchResponse, BranchUpdate
from app.schemas.company_settings import CompanySettingsResponse, CompanySettingsUpdate
from app.schemas.delivery import (
    DeliveryCreate,
    DeliveryNotifyRequest,
    DeliveryStatusUpdate,
    DeliveryUpdate,
)
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate
from app.schemas.seller import SellerCreate, SellerResponse, SellerUpdate
from app.schemas.user import UserImportRequest, UserImportSummary
from app.security import AdminContext, require_admin, require_admin_mutation, require_csrf_token
from app.services.asaas_client import AsaasIntegrationError
from app.services.branch_service import BranchService
from app.services.client_import_service import ClientImportService
from app.services.company_settings_service import CompanySettingsService
from app.services.delivery_service import DeliveryService
from app.services.payment_service import PaymentService
from app.services.product_service import ProductService
from app.services.seller_service import SellerService

router = APIRouter(prefix="/admin", tags=["admin"])


templates = Jinja2Templates(directory="app/admin/templates")



async def _access_form(request: Request) -> dict[str, str]:
    # These browser forms use the default URL-encoded format, with no uploads.
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
        return {}
    try:
        fields = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True, max_num_fields=10)
    except (UnicodeDecodeError, ValueError):
        return {}
    return {name: values[0] for name, values in fields.items() if len(values) == 1}


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request, db: Session = Depends(get_db)):
    form = await _access_form(request)
    account = authenticate_admin(db, form.get("username", ""), form.get("password", ""), datetime.now(UTC))
    if account is None:
        return templates.TemplateResponse(
            request=request, name="login.html", status_code=400,
            context={"error": "Não foi possível entrar. Confira os dados ou tente novamente mais tarde."},
        )
    request.session.clear()
    request.session.update({
        "admin_account_id": account.id,
        "auth_version": account.auth_version,
        "csrf_token": secrets.token_urlsafe(32),
    })
    return RedirectResponse("/admin", status_code=303)


@router.get("/recover", response_class=HTMLResponse)
async def recover_page(request: Request):
    return templates.TemplateResponse(request=request, name="recover.html")


@router.post("/recover", response_class=HTMLResponse)
async def recover(request: Request, db: Session = Depends(get_db)):
    form = await _access_form(request)
    expected_key = request.app.state.settings.admin_recovery_key
    key_matches = hmac.compare_digest(form.get("recovery_key", "").encode(), expected_key.encode())
    account = db.get(AdminAccount, 1, populate_existing=True)
    new_password = form.get("new_password", "")
    if (
        not expected_key
        or not key_matches
        or account is None
        or account.username != form.get("username", "")
        or len(new_password) < 12
        or new_password != form.get("confirm_password", "")
    ):
        return templates.TemplateResponse(
            request=request, name="recover.html", status_code=400,
            context={"error": "Não foi possível recuperar o acesso. Confira os dados e tente novamente."},
        )
    change_admin_password(db, account, new_password)
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.post("/logout")
async def logout(request: Request, context: AdminContext = Depends(require_admin)):
    if context.method == "session" and "X-CSRF-Token" not in request.headers:
        form = await _access_form(request)
        expected = context.csrf_token
        if not expected or not hmac.compare_digest(form.get("csrf_token", "").encode(), expected.encode()):
            raise HTTPException(status_code=403, detail="Admin access denied")
    else:
        require_csrf_token(request, context)
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/password", response_class=HTMLResponse)
async def password_page(request: Request, context: AdminContext = Depends(require_admin)):
    if context.method != "session":
        raise HTTPException(status_code=403, detail="Entre com sua sessão para alterar a senha.")
    return templates.TemplateResponse(
        request=request, name="password.html", context={"changed": request.query_params.get("changed") == "1"},
    )


@router.post("/password", response_class=HTMLResponse)
async def password_change(
    request: Request, context: AdminContext = Depends(require_admin), db: Session = Depends(get_db),
):
    if context.method != "session" or context.account is None:
        raise HTTPException(status_code=403, detail="Entre com sua sessão para alterar a senha.")
    form = await _access_form(request)
    supplied_token = request.headers.get("X-CSRF-Token", form.get("csrf_token", ""))
    if not context.csrf_token or not hmac.compare_digest(supplied_token.encode(), context.csrf_token.encode()):
        return templates.TemplateResponse(
            request=request, name="password.html", status_code=403,
            context={"error": "Não foi possível validar o formulário. Atualize a página e tente novamente."},
        )
    account = context.account
    # Hold the account lock through verification and the password/version update.
    db.refresh(account, with_for_update=True)
    if account.auth_version != request.session.get("auth_version"):
        request.session.clear()
        raise HTTPException(status_code=401, detail="Sua sessão expirou. Entre novamente.")
    new_password = form.get("new_password", "")
    if not verify_password(form.get("current_password", ""), account.password_hash):
        error = "A senha atual está incorreta. Confira e tente novamente."
    elif len(new_password) < 12:
        error = "A nova senha deve ter pelo menos 12 caracteres."
    elif new_password != form.get("confirm_password", ""):
        error = "A confirmação da nova senha não confere."
    else:
        error = None
    if error:
        return templates.TemplateResponse(
            request=request, name="password.html", status_code=400, context={"error": error},
        )
    change_admin_password(db, account, new_password)
    request.session.clear()
    request.session.update({
        "admin_account_id": account.id,
        "auth_version": account.auth_version,
        "csrf_token": secrets.token_urlsafe(32),
    })
    return RedirectResponse("/admin/password?changed=1", status_code=303)


@router.get("", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def dashboard(request: Request, db: Session = Depends(get_db)):
    service = AdminService(db)
    kpis = service.get_kpis()
    professionals: list[dict] = []

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "kpis": kpis,
        "professionals": professionals,
    })


@router.get("/appointments", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def appointments_page(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    professional_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    hide_unpaid_cancelled: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    appointments, total = service.list_appointments(
        date_from=date_from,
        date_to=date_to,
        professional_id=professional_id,
        status=status,
        search=search,
        hide_unpaid_cancelled=hide_unpaid_cancelled,
        page=page,
        page_size=page_size,
    )
    professionals: list[dict] = []
    appointment_options = {
        "professionals": [],
        "services": [],
        "clients": [
            {"id": client.id, "name": client.name, "masked_phone":
                client.phone[:4] + "••••" + client.phone[-3:]}
            for client in db.query(User)
            .filter(User.active.is_(True))
            .order_by(User.name)
            .all()
        ],
    }

    total_pages = (total + page_size - 1) // page_size

    return templates.TemplateResponse("appointments.html", {
        "request": request,
        "appointments": appointments,
        "professionals": professionals,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "filters": {
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "professional_id": professional_id or "",
            "status": status or "",
            "search": search or "",
            "hide_unpaid_cancelled": hide_unpaid_cancelled,
        },
        "appointment_options": appointment_options,
    })


@router.get("/clients", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def clients_page(request: Request):
    return templates.TemplateResponse(request=request, name="users.html")


@router.get("/stores", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def stores_page(request: Request):
    return templates.TemplateResponse(request=request, name="stores.html")


@router.get("/sellers", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def sellers_page(request: Request):
    return templates.TemplateResponse(request=request, name="sellers.html")


@router.get("/logistics", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def logistics_page(request: Request):
    return templates.TemplateResponse(request=request, name="logistics.html")


@router.get("/appointments/{appointment_id}", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def appointment_detail(
    request: Request,
    appointment_id: int,
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    detail = service.get_appointment_detail(appointment_id)

    if not detail:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")

    return templates.TemplateResponse("appointment_detail.html", {
        "request": request,
        "detail": jsonable_encoder(detail),
    })


@router.post("/appointments/{appointment_id}/action", dependencies=[Depends(require_admin_mutation)])
async def appointment_action(
    appointment_id: int,
    action: AppointmentAction,
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    result = service.appointment_action(appointment_id, action.action, action.notes)

    if result is None:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.get("/payments", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def payments_page(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    date_type: str = "payment",
    professional_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    payments, total, summary = service.list_payments(
        date_from=date_from,
        date_to=date_to,
        date_type=date_type,
        professional_id=professional_id,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )
    professionals: list[dict] = []

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return templates.TemplateResponse("payments.html", {
        "request": request,
        "payments": jsonable_encoder(payments),
        "professionals": jsonable_encoder(professionals),
        "total": total,
        "summary": jsonable_encoder(summary),
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "filters": {
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "date_type": date_type or "payment",
            "professional_id": professional_id or "",
            "status": status or "",
            "search": search or "",
        },
    })


@router.post(
    "/payments/{payment_id}/action",
    response_model=PaymentActionResult,
    dependencies=[Depends(require_admin_mutation)],
)
async def payment_action(
    payment_id: int,
    action: PaymentAction,
    db: Session = Depends(get_db),
):
    current_payment = db.get(Payment, payment_id)
    if current_payment is None:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")

    previous_status = current_payment.status
    service = PaymentService(db)
    try:
        if action.action == "refresh":
            payment = await service.refresh(payment_id)
        else:
            payment = await service.refund(payment_id)
    except AsaasIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    status_labels = {
        "pending": "pendente",
        "confirmed": "confirmado",
        "received": "recebido",
        "overdue": "vencido",
        "refunded": "estornado",
        "cancelled": "cancelado",
    }
    changed = previous_status != payment.status
    status_label = status_labels.get(payment.status, payment.status)
    if action.action == "refresh":
        prefix = "Pagamento sincronizado" if changed else "Pagamento já estava atualizado"
        message = f"{prefix}: {status_label}."
    else:
        message = f"Pagamento estornado: {status_label}."
    serialized = AdminService(db).get_payment(payment.id)
    if serialized is None:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    return {"message": message, "changed": changed, "payment": serialized}




@router.get("/products", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def products_page(request: Request, db: Session = Depends(get_db)):
    service = ProductService(db)
    products = service.list_products(active_only=False)
    categories = service.list_categories()
    serialized_products = jsonable_encoder([ProductResponse.model_validate(p) for p in products])
    return templates.TemplateResponse(
        request=request,
        name="products.html",
        context={
            "products": serialized_products,
            "categories": categories,
        },
    )


@router.post("/api/products", dependencies=[Depends(require_admin_mutation)])
async def api_create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    service = ProductService(db)
    product = service.create(payload)
    return jsonable_encoder(ProductResponse.model_validate(product))


@router.put("/api/products/{product_id}", dependencies=[Depends(require_admin_mutation)])
async def api_update_product(
    product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)
):
    service = ProductService(db)
    product = service.update(product_id, payload)
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return jsonable_encoder(ProductResponse.model_validate(product))


@router.post("/api/products/{product_id}/stock", dependencies=[Depends(require_admin_mutation)])
async def api_adjust_product_stock(
    product_id: int, request: Request, db: Session = Depends(get_db)
):
    body = await request.json()
    delta = body.get("quantity_delta", 0)
    service = ProductService(db)
    try:
        product = service.adjust_stock(product_id, int(delta))
        return jsonable_encoder(ProductResponse.model_validate(product))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/products/{product_id}/toggle-active", dependencies=[Depends(require_admin_mutation)])
async def api_toggle_product_active(product_id: int, db: Session = Depends(get_db)):
    service = ProductService(db)
    product = service.get_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    product.active = not product.active
    db.commit()
    db.refresh(product)
    return jsonable_encoder(ProductResponse.model_validate(product))


# -------------------------------------------------------------------------
# Gestão de Filiais (Branches)
# -------------------------------------------------------------------------

@router.get("/api/branches", dependencies=[Depends(require_admin)])
async def api_list_branches(
    search: str | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    service = BranchService(db)
    branches = service.list_branches(search=search, active_only=active_only)
    return [jsonable_encoder(BranchResponse.model_validate(b)) for b in branches]


@router.post("/api/branches", dependencies=[Depends(require_admin_mutation)])
async def api_create_branch(payload: BranchCreate, db: Session = Depends(get_db)):
    service = BranchService(db)
    try:
        branch = service.create(payload)
        return jsonable_encoder(BranchResponse.model_validate(branch))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/branches/{branch_id}", dependencies=[Depends(require_admin)])
async def api_get_branch(branch_id: int, db: Session = Depends(get_db)):
    service = BranchService(db)
    branch = service.get_by_id(branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Filial não encontrada")
    return jsonable_encoder(BranchResponse.model_validate(branch))


@router.put("/api/branches/{branch_id}", dependencies=[Depends(require_admin_mutation)])
async def api_update_branch(branch_id: int, payload: BranchUpdate, db: Session = Depends(get_db)):
    service = BranchService(db)
    try:
        branch = service.update(branch_id, payload)
        if not branch:
            raise HTTPException(status_code=404, detail="Filial não encontrada")
        return jsonable_encoder(BranchResponse.model_validate(branch))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/branches/{branch_id}", dependencies=[Depends(require_admin_mutation)])
async def api_delete_branch(branch_id: int, db: Session = Depends(get_db)):
    service = BranchService(db)
    deleted = service.delete(branch_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Filial não encontrada")
    return {"status": "success", "message": "Filial removida com sucesso"}


# -------------------------------------------------------------------------
# Gestão de Vendedores (Sellers)
# -------------------------------------------------------------------------

@router.get("/api/sellers", dependencies=[Depends(require_admin)])
async def api_list_sellers(
    branch_id: int | None = None,
    active_only: bool = False,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    service = SellerService(db)
    sellers = service.list_sellers(branch_id=branch_id, active_only=active_only, search=search)
    return [jsonable_encoder(SellerResponse.model_validate(s)) for s in sellers]


@router.post("/api/sellers", dependencies=[Depends(require_admin_mutation)])
async def api_create_seller(payload: SellerCreate, db: Session = Depends(get_db)):
    service = SellerService(db)
    try:
        seller = service.create(payload)
        return jsonable_encoder(SellerResponse.model_validate(seller))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/sellers/{seller_id}", dependencies=[Depends(require_admin)])
async def api_get_seller(seller_id: int, db: Session = Depends(get_db)):
    service = SellerService(db)
    seller = service.get_by_id(seller_id)
    if not seller:
        raise HTTPException(status_code=404, detail="Vendedor não encontrado")
    return jsonable_encoder(SellerResponse.model_validate(seller))


@router.put("/api/sellers/{seller_id}", dependencies=[Depends(require_admin_mutation)])
async def api_update_seller(seller_id: int, payload: SellerUpdate, db: Session = Depends(get_db)):
    service = SellerService(db)
    try:
        seller = service.update(seller_id, payload)
        if not seller:
            raise HTTPException(status_code=404, detail="Vendedor não encontrado")
        return jsonable_encoder(SellerResponse.model_validate(seller))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/sellers/{seller_id}", dependencies=[Depends(require_admin_mutation)])
async def api_delete_seller(seller_id: int, db: Session = Depends(get_db)):
    service = SellerService(db)
    deleted = service.delete(seller_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Vendedor não encontrado")
    return {"status": "success", "message": "Vendedor removido com sucesso"}


@router.get("/api/sellers/{seller_id}/metrics", dependencies=[Depends(require_admin)])
async def api_seller_metrics(seller_id: int, db: Session = Depends(get_db)):
    service = SellerService(db)
    try:
        return jsonable_encoder(service.get_metrics(seller_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==========================================================
# Gestão de Logística & Entregas (Deliveries & Dispatch)
# ==========================================================

@router.get("/api/deliveries", dependencies=[Depends(require_admin)])
async def api_list_deliveries(
    delivery_status: str | None = None,
    payment_timing: str | None = None,
    payment_status: str | None = None,
    branch_id: int | None = None,
    seller_id: int | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    service = DeliveryService(db)
    deliveries = service.list_deliveries(
        delivery_status=delivery_status,
        payment_timing=payment_timing,
        payment_status=payment_status,
        branch_id=branch_id,
        seller_id=seller_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    return jsonable_encoder(deliveries)


@router.get("/api/deliveries/kpis", dependencies=[Depends(require_admin)])
async def api_delivery_kpis(db: Session = Depends(get_db)):
    service = DeliveryService(db)
    return jsonable_encoder(service.get_kpis())


@router.post("/api/deliveries", dependencies=[Depends(require_admin_mutation)])
async def api_create_delivery(payload: DeliveryCreate, db: Session = Depends(get_db)):
    service = DeliveryService(db)
    try:
        created = service.create_delivery(payload)
        return jsonable_encoder(created)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/deliveries/{delivery_id}", dependencies=[Depends(require_admin)])
async def api_get_delivery(delivery_id: int, db: Session = Depends(get_db)):
    service = DeliveryService(db)
    delivery = service.get_delivery(delivery_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega não encontrada")
    return jsonable_encoder(delivery)


@router.put("/api/deliveries/{delivery_id}", dependencies=[Depends(require_admin_mutation)])
async def api_update_delivery(
    delivery_id: int, payload: DeliveryUpdate, db: Session = Depends(get_db)
):
    service = DeliveryService(db)
    updated = service.update_delivery(delivery_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Entrega não encontrada")
    return jsonable_encoder(updated)


@router.patch("/api/deliveries/{delivery_id}/status", dependencies=[Depends(require_admin_mutation)])
async def api_update_delivery_status(
    delivery_id: int, payload: DeliveryStatusUpdate, db: Session = Depends(get_db)
):
    service = DeliveryService(db)
    updated = service.update_status(
        delivery_id=delivery_id,
        delivery_status=payload.delivery_status,
        payment_status=payload.payment_status,
        delivery_driver_name=payload.delivery_driver_name,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Entrega não encontrada")
    return jsonable_encoder(updated)


@router.post("/api/deliveries/{delivery_id}/notify", dependencies=[Depends(require_admin_mutation)])
async def api_notify_delivery_dispatch(
    delivery_id: int, payload: DeliveryNotifyRequest | None = None, db: Session = Depends(get_db)
):
    service = DeliveryService(db)
    try:
        custom_msg = payload.custom_message if payload else None
        res = await service.notify_dispatch_via_whatsapp(delivery_id, custom_message=custom_msg)
        return jsonable_encoder(res)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar notificação WhatsApp: {e}")


@router.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def settings_page(request: Request, db: Session = Depends(get_db)):
    service = CompanySettingsService(db)
    settings = service.get_or_create_default()
    serialized_settings = jsonable_encoder(CompanySettingsResponse.model_validate(settings))
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": serialized_settings,
        },
    )


@router.post("/api/settings", dependencies=[Depends(require_admin_mutation)])
async def api_update_settings(payload: CompanySettingsUpdate, db: Session = Depends(get_db)):
    service = CompanySettingsService(db)
    settings = service.update(payload)
    return jsonable_encoder(CompanySettingsResponse.model_validate(settings))




# --- API Endpoints para HTMX partials ---

@router.get(
    "/api/clients",
    response_model=AdminClientPage,
    dependencies=[Depends(require_admin)],
)
async def api_clients(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    status: Literal["active", "archived", "all"] = "active",
    db: Session = Depends(get_db),
):
    clients, total = AdminService(db).list_clients(
        page=page, page_size=page_size, search=search, status=status
    )
    return {
        "data": clients,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


def _client_summary(db: Session, client: User) -> dict:
    summaries, _total = AdminService(db).list_clients(search=client.phone, status="all")
    return next(item for item in summaries if item["id"] == client.id)


@router.post(
    "/api/clients",
    response_model=AdminClientSummary,
    status_code=201,
    dependencies=[Depends(require_admin_mutation)],
)
async def create_admin_client(data: AdminClientCreate, db: Session = Depends(get_db)):
    try:
        client = AdminService(db).create_client(data)
    except (IntegrityError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Telefone ou e-mail já cadastrado.") from exc
    return _client_summary(db, client)


@router.post(
    "/api/clients/import",
    response_model=UserImportSummary,
    dependencies=[Depends(require_admin_mutation)],
)
async def api_import_clients_json(
    data: UserImportRequest,
    db: Session = Depends(get_db),
):
    return ClientImportService(db).import_items(data)


@router.post(
    "/api/clients/import/csv",
    response_model=UserImportSummary,
    dependencies=[Depends(require_admin_mutation)],
)
async def api_import_clients_csv(
    file: UploadFile = File(...),
    source: str = Query("import_csv"),
    deduplication_strategy: str = Query("update", pattern="^(update|skip|error)$"),
    import_batch_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        content_bytes = await file.read()
        csv_text = content_bytes.decode("utf-8-sig", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Erro ao ler arquivo CSV: {exc}") from exc

    return ClientImportService(db).import_csv_content(
        csv_text=csv_text,
        source=source,
        deduplication_strategy=deduplication_strategy,
        import_batch_id=import_batch_id,
    )



@router.put(
    "/api/clients/{client_id}",
    response_model=AdminClientSummary,
    dependencies=[Depends(require_admin_mutation)],
)
async def update_admin_client(
    client_id: int, data: AdminClientUpdate, db: Session = Depends(get_db)
):
    try:
        client = AdminService(db).update_client(client_id, data)
    except (IntegrityError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Telefone ou e-mail já cadastrado.") from exc
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return _client_summary(db, client)


@router.delete("/api/clients/{client_id}", dependencies=[Depends(require_admin_mutation)])
async def delete_admin_client(client_id: int, db: Session = Depends(get_db)):
    try:
        outcome = AdminService(db).archive_or_delete_user(client_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if outcome is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return {"outcome": outcome}


@router.post(
    "/api/clients/{client_id}/reactivate",
    response_model=AdminClientSummary,
    dependencies=[Depends(require_admin_mutation)],
)
async def reactivate_admin_client(client_id: int, db: Session = Depends(get_db)):
    client = AdminService(db).reactivate_user(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return _client_summary(db, client)


@router.post(
    "/api/appointments",
    status_code=201,
    dependencies=[Depends(require_admin_mutation)],
)
async def create_admin_appointment(
    data: AdminAppointmentCreate, db: Session = Depends(get_db)
):
    try:
        return AdminService(db).create_appointment(data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/api/appointments/{appointment_id}", dependencies=[Depends(require_admin_mutation)])
async def update_admin_appointment(
    appointment_id: int,
    data: AdminAppointmentUpdate,
    db: Session = Depends(get_db),
):
    try:
        appointment = AdminService(db).update_appointment(appointment_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not appointment:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    return appointment


@router.delete(
    "/api/appointments/{appointment_id}",
    status_code=204,
    dependencies=[Depends(require_admin_mutation)],
)
async def delete_admin_appointment(
    appointment_id: int, db: Session = Depends(get_db)
):
    try:
        deleted = AdminService(db).delete_appointment(appointment_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")


@router.get("/api/kpis", dependencies=[Depends(require_admin)])
async def api_kpis(db: Session = Depends(get_db)):
    service = AdminService(db)
    return service.get_kpis()


@router.get(
    "/api/system-status",
    response_model=AdminSystemStatus,
    dependencies=[Depends(require_admin)],
)
async def api_system_status(request: Request, db: Session = Depends(get_db)):
    return AdminService(db).get_system_status(request.app.state.settings)


@router.get("/api/appointments", dependencies=[Depends(require_admin)])
async def api_appointments(
    date_from: date | None = None,
    date_to: date | None = None,
    professional_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    hide_unpaid_cancelled: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    appointments, total = service.list_appointments(
        date_from=date_from,
        date_to=date_to,
        professional_id=professional_id,
        status=status,
        search=search,
        hide_unpaid_cancelled=hide_unpaid_cancelled,
        page=page,
        page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size
    return {
        "data": appointments,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get(
    "/api/payments",
    response_model=AdminPaymentsResponse,
    dependencies=[Depends(require_admin)],
)
async def api_payments(
    date_from: date | None = None,
    date_to: date | None = None,
    date_type: str = "payment",
    professional_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    payments, total, summary = service.list_payments(
        date_from=date_from,
        date_to=date_to,
        date_type=date_type,
        professional_id=professional_id,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    return {
        "data": payments,
        "total": total,
        "summary": summary,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/api/professionals", dependencies=[Depends(require_admin)])
async def api_professionals(
    limit: int | None = Query(None, ge=1, le=5),
    db: Session = Depends(get_db),
):
    return []


# ----------------------------------------------------------------------
# Manutenção & Retenção de Dados do Banco
# ----------------------------------------------------------------------
@router.get("/maintenance", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def maintenance_page(request: Request):
    six_months_ago = (datetime.now(UTC) - timedelta(days=180)).date().isoformat()
    return templates.TemplateResponse("maintenance.html", {
        "request": request,
        "default_cutoff_date": six_months_ago,
    })


@router.get(
    "/api/maintenance/preview",
    response_model=AdminMaintenancePreview,
    dependencies=[Depends(require_admin)],
)
async def api_maintenance_preview(
    cutoff_date: str | None = None,
    months: int | None = None,
    unpaid_cancelled_only: bool = False,
    db: Session = Depends(get_db),
):
    if months:
        target_dt = datetime.now(UTC) - timedelta(days=months * 30)
    elif cutoff_date:
        try:
            parsed_date = date.fromisoformat(cutoff_date)
            target_dt = datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)
        except ValueError:
            raise HTTPException(status_code=400, detail="Data de corte inválida (formato esperado: AAAA-MM-DD)")
    else:
        target_dt = datetime.now(UTC) - timedelta(days=180)

    service = AdminService(db)
    return service.preview_maintenance(target_dt, unpaid_cancelled_only=unpaid_cancelled_only)


@router.get("/api/maintenance/export-csv", dependencies=[Depends(require_admin)])
async def api_maintenance_export_csv(
    cutoff_date: str | None = None,
    months: int | None = None,
    unpaid_cancelled_only: bool = False,
    db: Session = Depends(get_db),
):
    if months:
        target_dt = datetime.now(UTC) - timedelta(days=months * 30)
    elif cutoff_date:
        try:
            parsed_date = date.fromisoformat(cutoff_date)
            target_dt = datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)
        except ValueError:
            raise HTTPException(status_code=400, detail="Data de corte inválida (formato esperado: AAAA-MM-DD)")
    else:
        target_dt = datetime.now(UTC) - timedelta(days=180)

    service = AdminService(db)
    csv_content = service.export_maintenance_csv(target_dt, unpaid_cancelled_only=unpaid_cancelled_only)
    filename = f"backup_agendamentos_{target_dt.strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


@router.post(
    "/api/maintenance/purge",
    response_model=AdminMaintenancePurgeResult,
    dependencies=[Depends(require_admin_mutation)],
)
async def api_maintenance_purge(
    payload: AdminMaintenancePurgeRequest,
    db: Session = Depends(get_db),
):
    if not payload.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirmação explícita necessária para executar a exclusão definitiva.",
        )

    try:
        parsed_date = date.fromisoformat(payload.cutoff_date)
        target_dt = datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)
    except ValueError:
        raise HTTPException(status_code=400, detail="Data de corte inválida (formato esperado: AAAA-MM-DD)")

    service = AdminService(db)
    return service.execute_maintenance_purge(
        target_dt,
        unpaid_cancelled_only=payload.unpaid_cancelled_only,
        run_vacuum=payload.run_vacuum,
    )
