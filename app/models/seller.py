from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Seller(Base):
    """
    Vendedor da filial.
    Possui suas credenciais para login na sua Área de Vendas,
    taxa de comissão personalizada, chave PIX para repasse e código de identificação.
    """

    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    cpf: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    # Comissão individual do vendedor (em %)
    commission_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.0)
    pix_key: Mapped[str | None] = mapped_column(String(100), nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    branch = relationship("Branch", back_populates="sellers")
    payments = relationship("Payment", back_populates="seller")

    @property
    def branch_name(self) -> str | None:
        return self.branch.name if self.branch else None

