from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.base import BaseRepository
from app.utils.sanitizers import clean_digits


def _generate_phone_candidates(phone: str) -> tuple[set[str], str | None]:
    """Gera variações de telefones brasileiros (com/sem DDI 55, com/sem 9º dígito, com/sem '+')."""
    if not phone or not str(phone).strip():
        return set(), None
    raw = str(phone).strip()
    digits = clean_digits(raw)
    if not digits:
        return set(), None

    candidates = {raw, digits, f"+{digits}"}
    d = digits
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]

    local8_suffix = None
    if len(d) == 11:  # DDD (2) + 9 dígitos
        ddd = d[:2]
        local9 = d[2:]
        local8 = d[3:] if local9.startswith("9") else d[2:]
        local8_suffix = local8
        for v in [
            f"{ddd}{local9}",
            f"{ddd}{local8}",
            f"55{ddd}{local9}",
            f"55{ddd}{local8}",
            local9,
            local8,
        ]:
            candidates.add(v)
            candidates.add(f"+{v}")
    elif len(d) == 10:  # DDD (2) + 8 dígitos
        ddd = d[:2]
        local8 = d[2:]
        local9 = f"9{local8}"
        local8_suffix = local8
        for v in [
            f"{ddd}{local8}",
            f"{ddd}{local9}",
            f"55{ddd}{local8}",
            f"55{ddd}{local9}",
            local8,
            local9,
        ]:
            candidates.add(v)
            candidates.add(f"+{v}")
    elif len(d) in (8, 9):
        if len(d) == 9 and d.startswith("9"):
            local8 = d[1:]
            local8_suffix = local8
            candidates.add(local8)
            candidates.add(f"+{local8}")
        elif len(d) == 8:
            local8 = d
            local8_suffix = local8
            candidates.add(f"9{local8}")
            candidates.add(f"+9{local8}")

    return candidates, local8_suffix


class UserRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, User)

    def find_by_cpf(self, cpf: str) -> User | None:
        if not cpf:
            return None
        raw = str(cpf).strip()
        digits = clean_digits(raw)
        if not digits or len(digits) < 11:
            return None
        return (
            self.db.query(User)
            .filter((User.cpf_cnpj == digits) | (User.cpf_cnpj == raw))
            .order_by(User.id.desc())
            .first()
        )

    def find_by_name(self, name: str) -> User | None:
        if not name or not str(name).strip():
            return None
        raw_name = str(name).strip()

        # 1. Substring direta
        user = (
            self.db.query(User)
            .filter(User.name.ilike(f"%{raw_name}%"))
            .order_by(User.id.desc())
            .first()
        )
        if user:
            return user

        # 2. Busca por palavras (tokens) caso tenha informado nome composto
        tokens = [t for t in raw_name.split() if len(t) >= 3]
        for token in reversed(tokens):
            user = (
                self.db.query(User)
                .filter(User.name.ilike(f"%{token}%"))
                .order_by(User.id.desc())
                .first()
            )
            if user:
                return user
        return None

    def find_by_identifier(
        self,
        query: str | None = None,
        phone: str | None = None,
        name: str | None = None,
        cpf_cnpj: str | None = None,
    ) -> User | None:
        if cpf_cnpj:
            user = self.find_by_cpf(cpf_cnpj)
            if user:
                return user

        if phone:
            user = self.find_by_phone(phone)
            if user:
                return user

        if name:
            user = self.find_by_name(name)
            if user:
                return user

        if query:
            q_clean = str(query).strip()
            q_digits = clean_digits(q_clean)
            if q_digits and len(q_digits) in (11, 14):
                user = self.find_by_cpf(q_digits)
                if user:
                    return user
            user = self.find_by_phone(q_clean)
            if user:
                return user
            user = self.find_by_name(q_clean)
            if user:
                return user

        return None

    def find_by_phone(self, phone: str):
        if not phone or not str(phone).strip():
            return None
        raw_query = str(phone).strip()
        digits = clean_digits(raw_query)

        # Se passou um CPF ou CNPJ válido no campo phone/query
        if digits and len(digits) in (11, 14):
            user_cpf = self.find_by_cpf(digits)
            if user_cpf:
                return user_cpf

        candidates, local8_suffix = _generate_phone_candidates(raw_query)
        if candidates:
            # 1. Busca exata pelas variações de telefone
            user = (
                self.db.query(User)
                .filter(
                    (User.phone.in_(candidates))
                    | (User.whatsapp_number.in_(candidates))
                )
                .order_by(User.id.desc())
                .first()
            )
            if user:
                return user

            # 2. Busca por sufixo dos últimos 8 dígitos (independente de DDD ou 9º dígito)
            search_suffix = local8_suffix or (digits if digits and len(digits) in (8, 9) else None)
            if search_suffix:
                user = (
                    self.db.query(User)
                    .filter(
                        (User.phone.like(f"%{search_suffix}"))
                        | (User.whatsapp_number.like(f"%{search_suffix}"))
                    )
                    .order_by(User.id.desc())
                    .first()
                )
                if user:
                    return user

        # 3. Fallback: Busca por nome do cliente
        if len(raw_query) >= 3 and any(c.isalpha() for c in raw_query):
            user = self.find_by_name(raw_query)
            if user:
                return user

        return None

    def find_active_by_phone(self, phone: str):
        user = self.find_by_phone(phone)
        if user and getattr(user, "active", True):
            return user
        return None
