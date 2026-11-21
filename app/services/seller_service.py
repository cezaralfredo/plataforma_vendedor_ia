import logging
from datetime import UTC, datetime

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, joinedload

from app.admin.auth import verify_password as verify_legacy_pbkdf2
from app.admin.auth_service import (
    LOGIN_FAILURE_LIMIT,
    LOGIN_LOCK_DURATION,
    hash_password,
    verify_password,
)
from app.models.branch import Branch
from app.models.delivery import Delivery
from app.models.payment import Payment
from app.models.seller import Seller
from app.schemas.seller import (
    SellerCreate,
    SellerMetricsResponse,
    SellerUpdate,
)

logger = logging.getLogger(__name__)


def _verify_seller_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """Valida senha (scrypt-v1 atual ou pbkdf2 legado). Retorna (valido, precisa_upgrade)."""
    if stored_hash.startswith("scrypt-v1$"):
        return verify_password(password, stored_hash), False
    if stored_hash.startswith("pbkdf2_sha256$"):
        return verify_legacy_pbkdf2(password, stored_hash), True
    return False, False


class SellerService:
    """Serviço de gerenciamento, autenticação e métricas de Vendedores."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, data: SellerCreate) -> Seller:
        branch = self.db.query(Branch).filter(Branch.id == data.branch_id).first()
        if not branch:
            raise ValueError(f"Filial com ID {data.branch_id} não encontrada.")

        clean_email = data.email.lower().strip()
        if self.db.query(Seller).filter(Seller.email == clean_email).first():
            raise ValueError(f"O e-mail '{clean_email}' já está em uso por outro vendedor.")

        clean_code = data.code.strip().upper()
        if self.db.query(Seller).filter(Seller.code == clean_code).first():
            raise ValueError(f"O código de vendedor '{clean_code}' já está cadastrado.")

        seller = Seller(
            branch_id=data.branch_id,
            name=data.name.strip(),
            email=clean_email,
            password_hash=hash_password(data.password),
            phone=data.phone.strip() if data.phone else None,
            whatsapp_number=data.whatsapp_number.strip(),
            cpf=data.cpf.strip() if data.cpf else None,
            code=clean_code,
            commission_rate=data.commission_rate,
            pix_key=data.pix_key.strip() if data.pix_key else None,
            active=data.active,
        )
        self.db.add(seller)
        self.db.commit()
        self.db.refresh(seller)
        return seller

    def authenticate(self, email: str, password: str) -> Seller | None:
        clean_email = email.lower().strip()
        seller = self.db.query(Seller).filter(Seller.email == clean_email, Seller.active.is_(True)).first()
        if not seller:
            return None

        now = datetime.now(UTC)
        if seller.locked_until is not None:
            locked_until = seller.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=UTC)
            if locked_until > now:
                return None

        valid, needs_upgrade = _verify_seller_password(password, seller.password_hash)
        if not valid:
            seller.failed_login_count = (seller.failed_login_count or 0) + 1
            if seller.failed_login_count >= LOGIN_FAILURE_LIMIT:
                seller.locked_until = now + LOGIN_LOCK_DURATION
            self.db.commit()
            return None

        if needs_upgrade:
            seller.password_hash = hash_password(password)
        seller.failed_login_count = 0
        seller.locked_until = None
        seller.last_login_at = now
        self.db.commit()
        return seller

    def get_by_id(self, seller_id: int) -> Seller | None:
        return (
            self.db.query(Seller)
            .options(joinedload(Seller.branch))
            .filter(Seller.id == seller_id)
            .first()
        )

    def get_by_code(self, code: str) -> Seller | None:
        return self.db.query(Seller).filter(Seller.code == code.strip().upper()).first()

    def get_by_whatsapp(self, phone: str) -> Seller | None:
        clean_phone = "".join(filter(str.isdigit, str(phone or "")))
        if len(clean_phone) < 8:
            return None
        return self.db.query(Seller).filter(Seller.whatsapp_number.like(f"%{clean_phone}")).first()

    def list_sellers(
        self,
        branch_id: int | None = None,
        active_only: bool = False,
        search: str | None = None,
    ) -> list[Seller]:
        q = self.db.query(Seller).options(joinedload(Seller.branch))
        if branch_id:
            q = q.filter(Seller.branch_id == branch_id)
        if active_only:
            q = q.filter(Seller.active.is_(True))
        if search:
            term = f"%{search.strip()}%"
            q = q.filter(
                or_(
                    Seller.name.ilike(term),
                    Seller.email.ilike(term),
                    Seller.code.ilike(term),
                    Seller.whatsapp_number.ilike(term),
                )
            )
        return q.order_by(Seller.name).all()

    def update(self, seller_id: int, data: SellerUpdate) -> Seller | None:
        seller = self.get_by_id(seller_id)
        if not seller:
            return None

        fields = data.model_dump(exclude_unset=True)

        if "branch_id" in fields and fields["branch_id"] is not None:
            branch = self.db.query(Branch).filter(Branch.id == fields["branch_id"]).first()
            if not branch:
                raise ValueError(f"Filial com ID {fields['branch_id']} não encontrada.")

        if fields.get("email"):
            new_email = fields["email"].lower().strip()
            if new_email != seller.email:
                if self.db.query(Seller).filter(Seller.email == new_email, Seller.id != seller.id).first():
                    raise ValueError(f"O e-mail '{new_email}' já está em uso.")
                fields["email"] = new_email

        if fields.get("code"):
            new_code = fields["code"].strip().upper()
            if new_code != seller.code:
                if self.db.query(Seller).filter(Seller.code == new_code, Seller.id != seller.id).first():
                    raise ValueError(f"O código '{new_code}' já está em uso.")
                fields["code"] = new_code

        if fields.get("password"):
            seller.password_hash = hash_password(fields.pop("password"))
            seller.auth_version = (seller.auth_version or 1) + 1
            seller.failed_login_count = 0
            seller.locked_until = None

        for key, val in fields.items():
            if isinstance(val, str) and key in {"name", "phone", "whatsapp_number", "cpf", "pix_key"}:
                val = val.strip()
            setattr(seller, key, val)

        self.db.commit()
        self.db.refresh(seller)
        return seller

    def delete(self, seller_id: int) -> bool:
        seller = self.get_by_id(seller_id)
        if not seller:
            return False
        has_history = (
            self.db.query(Payment.id).filter(Payment.seller_id == seller_id).first() is not None
            or self.db.query(Delivery.id).filter(Delivery.seller_id == seller_id).first() is not None
        )
        if has_history:
            seller.active = False
            seller.auth_version = (seller.auth_version or 1) + 1
            self.db.commit()
            return True
        self.db.delete(seller)
        self.db.commit()
        return True

    def get_metrics(self, seller_id: int) -> SellerMetricsResponse:
        seller = self.get_by_id(seller_id)
        if not seller:
            raise ValueError(f"Vendedor com ID {seller_id} não encontrado.")

        row = (
            self.db.query(
                func.count(case((Payment.status.in_(["received", "confirmed", "pending"]), 1))).label("total_orders"),
                func.coalesce(
                    func.sum(case((Payment.status.in_(["received", "confirmed"]), Payment.amount_cents), else_=0)),
                    0,
                ).label("total_sales_cents"),
                func.coalesce(
                    func.sum(
                        case(
                            (Payment.status.in_(["received", "confirmed"]), func.coalesce(Payment.commission_amount_cents, 0)),
                            else_=0,
                        )
                    ),
                    0,
                ).label("paid_commission_cents"),
                func.coalesce(
                    func.sum(
                        case(
                            (Payment.status == "pending", func.coalesce(Payment.commission_amount_cents, 0)),
                            else_=0,
                        )
                    ),
                    0,
                ).label("pending_commission_cents"),
            )
            .filter(Payment.seller_id == seller_id)
            .one()
        )

        total_orders_count = int(row.total_orders or 0)
        total_sales_cents = int(row.total_sales_cents or 0)
        paid_commission_cents = int(row.paid_commission_cents or 0)
        pending_commission_cents = int(row.pending_commission_cents or 0)
        total_commission_cents = paid_commission_cents + pending_commission_cents

        branch_name = seller.branch.name if seller.branch else "Matriz"

        return SellerMetricsResponse(
            seller_id=seller.id,
            seller_name=seller.name,
            branch_name=branch_name,
            total_sales_cents=total_sales_cents,
            total_orders_count=total_orders_count,
            total_commission_cents=total_commission_cents,
            paid_commission_cents=paid_commission_cents,
            pending_commission_cents=pending_commission_cents,
        )
