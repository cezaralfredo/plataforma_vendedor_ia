from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Branch(Base):
    """
    Filial da empresa / Loja física / Ponto de atendimento.
    Permite agrupar vendedores por unidade de negócio.
    """

    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    cnpj: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    neighborhood: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    sellers = relationship("Seller", back_populates="branch", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="branch")

    @property
    def sellers_count(self) -> int:
        return len(self.sellers) if self.sellers else 0

    @property
    def active_sellers_count(self) -> int:
        return len([s for s in self.sellers if s.active]) if self.sellers else 0

    @property
    def full_address(self) -> str:
        parts = []
        if self.address:
            addr = self.address
            if self.address_number:
                addr += f", {self.address_number}"
            parts.append(addr)
        if self.neighborhood:
            parts.append(self.neighborhood)
        city_state = " - ".join(filter(None, [self.city, self.state]))
        if city_state:
            parts.append(city_state)
        if self.postal_code:
            parts.append(f"CEP: {self.postal_code}")
        return ", ".join(parts) if parts else (self.address or "")

