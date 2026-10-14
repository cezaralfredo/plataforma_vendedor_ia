from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.user import User
from app.repositories import UserRepository
from app.repositories.base import RelatedRecordsError
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, db: Session):
        self.repo = UserRepository(db)

    def find_by_phone(self, phone: str) -> User | None:
        return self.repo.find_active_by_phone(phone)

    def find_by_cpf(self, cpf: str) -> User | None:
        return self.repo.find_by_cpf(cpf)

    def find_by_name(self, name: str) -> User | None:
        return self.repo.find_by_name(name)

    def find_by_identifier(
        self,
        query: str | None = None,
        phone: str | None = None,
        name: str | None = None,
        cpf_cnpj: str | None = None,
    ) -> User | None:
        return self.repo.find_by_identifier(
            query=query, phone=phone, name=name, cpf_cnpj=cpf_cnpj
        )

    def get_by_phone(self, phone: str) -> User | None:
        return self.repo.find_by_phone(phone)

    def get(self, user_id: int) -> User | None:
        return self.repo.get(user_id)

    def create(self, data: UserCreate) -> User:
        dump = data.model_dump()
        if self.repo.find_by_phone(dump["phone"]):
            raise ValueError("Telefone já cadastrado")
        if dump.get("cpf_cnpj"):
            existing_cpf = self.repo.find_by_cpf(dump["cpf_cnpj"])
            if existing_cpf:
                raise ValueError(
                    f"CPF/CNPJ já cadastrado para o cliente '{existing_cpf.name}' (ID #{existing_cpf.id})"
                )
        if dump.get("email"):
            existing_email = self.repo.db.query(User).filter(User.email == dump["email"]).first()
            if existing_email:
                raise ValueError("E-mail já cadastrado por outro cliente")
        return self.repo.create(**dump)

    def update(self, user_id: int, data: UserUpdate) -> User | None:
        values = data.model_dump(exclude_unset=True)
        if values.get("phone"):
            existing = self.repo.find_by_phone(values["phone"])
            if existing and existing.id != user_id:
                raise ValueError("Telefone já cadastrado")
        if values.get("email"):
            existing_email = (
                self.repo.db.query(User)
                .filter(User.email == values["email"], User.id != user_id)
                .first()
            )
            if existing_email:
                raise ValueError("E-mail já cadastrado por outro cliente")
        return self.repo.update(user_id, **values)

    def link_whatsapp(self, user_id: int, whatsapp_number: str) -> User | None:
        return self.repo.update(user_id, whatsapp_number=whatsapp_number)

    def delete(self, user_id: int) -> bool:
        if self.repo.db.query(Appointment.id).filter(
            Appointment.user_id == user_id
        ).first():
            raise RelatedRecordsError(
                "Cliente possui agendamentos e não pode ser excluído"
            )
        return self.repo.delete(user_id)
