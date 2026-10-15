from typing import Any

from app.services.asaas_client import AsaasClient
from app.services.payment_gateways.base import BasePaymentGateway


class AsaasPaymentGateway(BasePaymentGateway):
    """Adapter para o Asaas implementando a interface unificada BasePaymentGateway."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.client = AsaasClient()
        if api_key:
            self.client.api_key = api_key
            self.client.headers["access_token"] = api_key
        if base_url:
            self.client.base_url = base_url.rstrip("/")

    async def create_charge(
        self,
        appointment_id: int,
        amount_cents: int,
        customer_info: dict[str, Any],
        billing_type: str = "pix",
    ) -> dict[str, Any]:
        customer_id = customer_info.get("customer_id")
        due_date = customer_info.get("due_date")

        res = await self.client.create_payment(
            customer_id=customer_id,
            billing_type=billing_type.upper(),
            value=amount_cents / 100.0,
            due_date=due_date,
            description=f"Agendamento #{appointment_id}",
            external_reference=f"appointment:{appointment_id}",
        )

        payment_id = res.get("id")
        pix_qr = None
        if billing_type.lower() == "pix" and payment_id:
            try:
                pix_qr = await self.client.get_pix_qr_code(payment_id)
            except Exception:  # noqa: S110
                pass

        return {
            "gateway_payment_id": payment_id,
            "status": "pending",
            "invoice_url": res.get("invoiceUrl"),
            "pix_copy_paste": pix_qr.get("payload") if pix_qr else None,
            "pix_qr_code_url": pix_qr.get("encodedImage") if pix_qr else None,
            "raw_response": res,
        }

    async def check_status(self, gateway_payment_id: str) -> dict[str, Any]:
        res = await self.client.get_payment(gateway_payment_id)
        return {
            "gateway_payment_id": gateway_payment_id,
            "status": res.get("status", "pending").lower(),
            "received_at": res.get("paymentDate"),
            "raw_response": res,
        }

    async def refund(self, gateway_payment_id: str, reason: str | None = None) -> dict[str, Any]:
        res = await self.client.refund_payment(gateway_payment_id, description=reason)
        return {
            "gateway_payment_id": gateway_payment_id,
            "status": "refunded",
            "raw_response": res,
        }
