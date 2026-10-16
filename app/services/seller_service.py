import logging
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.admin.auth import hash_password, verify_password
from app.models.branch import Branch
from app.models.payment import Payment
from app.models.seller import Seller
from app.schemas.seller import (
    SellerCreate,
    SellerMetricsResponse,
    SellerUpdate,
)

logger = logging.getLogger(__name__)


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

        if not verify_password(password, seller.password_hash):
            return None

        seller.last_login_at = datetime.now(UTC)
        self.db.commit()
        return seller

    def get_by_id(self, seller_id: int) -> Seller | None:
        return self.db.query(Seller).filter(Seller.id == seller_id).first()

    def get_by_code(self, code: str) -> Seller | None:
        return self.db.query(Seller).filter(Seller.code == code.strip().upper()).first()

    def get_by_whatsapp(self, phone: str) -> Seller | None:
        clean_phone = "".join(filter(str.isdigit, str(phone)))
        return self.db.query(Seller).filter(Seller.whatsapp_number.like(f"%{clean_phone}%")).first()

    def list_sellers(self, branch_id: int | None = None, active_only: bool = False) -> list[Seller]:
        q = self.db.query(Seller)
        if branch_id:
            q = q.filter(Seller.branch_id == branch_id)
        if active_only:
            q = q.filter(Seller.active.is_(True))
        return q.order_by(Seller.name).all()

    def update(self, seller_id: int, data: SellerUpdate) -> Seller | None:
        seller = self.get_by_id(seller_id)
        if not seller:
            return None

        fields = data.model_dump(exclude_unset=True)

        if "email" in fields and fields["email"]:
            new_email = fields["email"].lower().strip()
            if new_email != seller.email:
                if self.db.query(Seller).filter(Seller.email == new_email, Seller.id != seller.id).first():
                    raise ValueError(f"O e-mail '{new_email}' já está em uso.")
                fields["email"] = new_email

        if "code" in fields and fields["code"]:
            new_code = fields["code"].strip().upper()
            if new_code != seller.code:
                if self.db.query(Seller).filter(Seller.code == new_code, Seller.id != seller.id).first():
                    raise ValueError(f"O código '{new_code}' já está em uso.")
                fields["code"] = new_code

        if "password" in fields and fields["password"]:
            seller.password_hash = hash_password(fields.pop("password"))

        for key, val in fields.items():
            setattr(seller, key, val)

        self.db.commit()
        self.db.refresh(seller)
        return seller

    def delete(self, seller_id: int) -> bool:
        seller = self.get_by_id(seller_id)
        if not seller:
            return False
        self.db.delete(seller)
        self.db.commit()
        return True

    def get_metrics(self, seller_id: int) -> SellerMetricsResponse:
        seller = self.get_by_id(seller_id)
        if not seller:
            raise ValueError(f"Vendedor com ID {seller_id} não encontrado.")

        payments = self.db.query(Payment).filter(Payment.seller_id == seller_id).all()

        total_orders_count = len(payments)
        total_sales_cents = sum(
            p.amount_cents for p in payments if p.status in {"received", "confirmed"}
        )
        paid_commission_cents = sum(
            p.commission_amount_cents or 0
            for p in payments
            if p.status in {"received", "confirmed"}
        )
        pending_commission_cents = sum(
            p.commission_amount_cents or 0
            for p in payments
            if p.status == "pending"
        )
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
