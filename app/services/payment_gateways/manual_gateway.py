from datetime import datetime, timezone
from typing import Any

from app.services.payment_gateways.base import BasePaymentGateway


class ManualPaymentGateway(BasePaymentGateway):
    """Gateway de pagamento local / manual no balcão (sem cobrança online externa)."""

    async def create_charge(
        self,
        appointment_id: int,
        amount_cents: int,
        customer_info: dict[str, Any],
        billing_type: str = "in_person",
    ) -> dict[str, Any]:
        return {
            "gateway_payment_id": f"manual:{appointment_id}",
            "status": "confirmed",
            "invoice_url": None,
            "pix_copy_paste": None,
            "pix_qr_code_url": None,
            "message": "Pagamento a ser realizado diretamente no estabelecimento",
        }

    async def check_status(self, gateway_payment_id: str) -> dict[str, Any]:
        return {
            "gateway_payment_id": gateway_payment_id,
            "status": "confirmed",
            "received_at": datetime.now(timezone.utc),
        }

    async def refund(self, gateway_payment_id: str, reason: str | None = None) -> dict[str, Any]:
        return {
            "gateway_payment_id": gateway_payment_id,
            "status": "cancelled",
            "refunded": True,
        }
