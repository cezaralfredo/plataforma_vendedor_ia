from abc import ABC, abstractmethod
from typing import Any


class BasePaymentGateway(ABC):
    """Interface padrão para qualquer gateway de pagamento plugado na plataforma."""

    @abstractmethod
    async def create_charge(
        self,
        appointment_id: int,
        amount_cents: int,
        customer_info: dict[str, Any],
        billing_type: str = "pix",
    ) -> dict[str, Any]:
        """
        Cria uma cobrança no provedor selecionado.
        Retorno padrão esperado:
        {
            "gateway_payment_id": str,
            "status": "pending" | "confirmed" | "received",
            "invoice_url": str | None,
            "pix_copy_paste": str | None,
            "pix_qr_code_url": str | None
        }
        """
        pass

    @abstractmethod
    async def check_status(self, gateway_payment_id: str) -> dict[str, Any]:
        """
        Consulta o status atual de uma cobrança no provedor.
        Retorno padrão:
        {
            "gateway_payment_id": str,
            "status": "pending" | "confirmed" | "received" | "cancelled" | "refunded",
            "received_at": datetime | None
        }
        """
        pass

    @abstractmethod
    async def refund(self, gateway_payment_id: str, reason: str | None = None) -> dict[str, Any]:
        """Realiza estorno ou cancelamento da cobrança."""
        pass
