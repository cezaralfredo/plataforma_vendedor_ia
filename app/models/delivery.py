from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Delivery(Base):
    """
    Logística e Entregas de Pedidos.
    Controla o ciclo de separação, saída para entrega, notificação de cliente via WhatsApp
    e cobrança (antecipada ou no ato da entrega).
    """

    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    seller_id: Mapped[int | None] = mapped_column(ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True, index=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, index=True)

    items_description: Mapped[str] = mapped_column(Text, nullable=False)
    total_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Forma e Momento do Pagamento:
    # payment_timing: 'antecipado' ou 'na_entrega'
    payment_timing: Mapped[str] = mapped_column(String(20), nullable=False, default="na_entrega", server_default="na_entrega")
    # payment_method: 'pix', 'dinheiro', 'cartao_credito', 'cartao_debito'
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False, default="pix", server_default="pix")
    # payment_status: 'pago' ou 'pendente'
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente", server_default="pendente")

    # Status da Entrega:
    # 'preparando', 'a_caminho', 'entregue', 'cancelado'
    delivery_status: Mapped[str] = mapped_column(String(30), nullable=False, default="preparando", server_default="preparando")

    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_driver_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("User", backref="deliveries")
    branch = relationship("Branch", backref="deliveries")
    seller = relationship("Seller", backref="deliveries")
    payment = relationship("Payment", backref="deliveries")
