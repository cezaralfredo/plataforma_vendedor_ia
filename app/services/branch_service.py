import logging

from sqlalchemy.orm import Session

from app.models.branch import Branch
from app.schemas.branch import BranchCreate, BranchUpdate

logger = logging.getLogger(__name__)


class BranchService:
    """Serviço de gerenciamento de Filiais e Unidades de Negócio."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, data: BranchCreate) -> Branch:
        clean_code = data.code.strip().upper()
        existing = self.db.query(Branch).filter(Branch.code == clean_code).first()
        if existing:
            raise ValueError(f"Já existe uma filial cadastrada com o código '{clean_code}'.")

        branch = Branch(
            name=data.name.strip(),
            code=clean_code,
            cnpj=data.cnpj.strip() if data.cnpj else None,
            phone=data.phone.strip() if data.phone else None,
            whatsapp_number=data.whatsapp_number.strip() if data.whatsapp_number else None,
            email=data.email.strip() if data.email else None,
            postal_code=data.postal_code.strip() if data.postal_code else None,
            address=data.address.strip() if data.address else None,
            address_number=data.address_number.strip() if data.address_number else None,
            neighborhood=data.neighborhood.strip() if data.neighborhood else None,
            city=data.city.strip() if data.city else None,
            state=data.state.strip().upper()[:2] if data.state else None,
            active=data.active,
        )
        self.db.add(branch)
        self.db.commit()
        self.db.refresh(branch)
        return branch

    def get_by_id(self, branch_id: int) -> Branch | None:
        return self.db.query(Branch).filter(Branch.id == branch_id).first()

    def get_by_code(self, code: str) -> Branch | None:
        return self.db.query(Branch).filter(Branch.code == code.strip().upper()).first()

    def list_branches(
        self, search: str | None = None, active_only: bool = False
    ) -> list[Branch]:
        q = self.db.query(Branch)
        if active_only:
            q = q.filter(Branch.active.is_(True))
        if search:
            term = f"%{search.strip()}%"
            from sqlalchemy import or_
            q = q.filter(
                or_(
                    Branch.name.ilike(term),
                    Branch.code.ilike(term),
                    Branch.city.ilike(term),
                    Branch.address.ilike(term),
                )
            )
        return q.order_by(Branch.name).all()

    def update(self, branch_id: int, data: BranchUpdate) -> Branch | None:
        branch = self.get_by_id(branch_id)
        if not branch:
            return None

        fields = data.model_dump(exclude_unset=True)
        if fields.get("code"):
            new_code = fields["code"].strip().upper()
            if new_code != branch.code:
                collision = self.db.query(Branch).filter(Branch.code == new_code, Branch.id != branch.id).first()
                if collision:
                    raise ValueError(f"O código de loja '{new_code}' já está em uso.")
                fields["code"] = new_code
        if fields.get("state"):
            fields["state"] = str(fields["state"]).strip().upper()[:2]

        for key, val in fields.items():
            if isinstance(val, str):
                val = val.strip()
            setattr(branch, key, val)

        self.db.commit()
        self.db.refresh(branch)
        return branch

    def delete(self, branch_id: int) -> bool:
        branch = self.get_by_id(branch_id)
        if not branch:
            return False
        if branch.sellers:
            # Desativa para preservar integridade relacional
            branch.active = False
            self.db.commit()
            return True
        self.db.delete(branch)
        self.db.commit()
        return True
