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
            address=data.address.strip() if data.address else None,
            city=data.city.strip() if data.city else None,
            state=data.state.strip().upper() if data.state else None,
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

    def list_branches(self, active_only: bool = False) -> list[Branch]:
        q = self.db.query(Branch)
        if active_only:
            q = q.filter(Branch.active.is_(True))
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
                    raise ValueError(f"O código de filial '{new_code}' já está em uso.")
                fields["code"] = new_code

        for key, val in fields.items():
            setattr(branch, key, val)

        self.db.commit()
        self.db.refresh(branch)
        return branch

    def delete(self, branch_id: int) -> bool:
        branch = self.get_by_id(branch_id)
        if not branch:
            return False
        self.db.delete(branch)
        self.db.commit()
        return True
