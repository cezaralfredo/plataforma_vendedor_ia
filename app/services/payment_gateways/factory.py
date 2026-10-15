from typing import Any

from app.services.payment_gateways.asaas_gateway import AsaasPaymentGateway
from app.services.payment_gateways.base import BasePaymentGateway
from app.services.payment_gateways.manual_gateway import ManualPaymentGateway


def get_payment_gateway(
    provider: str = "asaas",
    credentials: dict[str, Any] | None = None,
) -> BasePaymentGateway:
    """Retorna a instância do gateway de pagamento com base no provedor configurado."""
    provider_normalized = (provider or "asaas").lower().strip()
    creds = credentials or {}

    if provider_normalized == "asaas":
        return AsaasPaymentGateway(
            api_key=creds.get("api_key"),
            base_url=creds.get("base_url"),
        )
    elif provider_normalized in {"manual", "none", "in_person", "balcao"}:
        return ManualPaymentGateway()
    else:
        # Fallback gracioso: se o provedor não for suportado diretamente ainda, usar Manual
        return ManualPaymentGateway()
