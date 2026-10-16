from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DeliveryBase(BaseModel):
    user_id: int
    branch_id: int | None = None
    seller_id: int | None = None
    payment_id: int | None = None
    items_description: str = Field(..., min_length=1)
    total_amount_cents: int = Field(0, ge=0)
    payment_method: Literal["pix", "dinheiro", "cartao_credito", "cartao_debito"] = "pix"
    payment_timing: Literal["antecipado", "na_entrega"] = "na_entrega"
    payment_status: Literal["pago", "pendente"] = "pendente"
    delivery_status: Literal["preparando", "a_caminho", "entregue", "cancelado"] = "preparando"
    delivery_address: str = Field(..., min_length=3)
    delivery_driver_name: str | None = None
    notes: str | None = None


class DeliveryCreate(DeliveryBase):
    pass


class DeliveryUpdate(BaseModel):
    items_description: str | None = None
    total_amount_cents: int | None = Field(None, ge=0)
    payment_method: Literal["pix", "dinheiro", "cartao_credito", "cartao_debito"] | None = None
    payment_timing: Literal["antecipado", "na_entrega"] | None = None
    payment_status: Literal["pago", "pendente"] | None = None
    delivery_status: Literal["preparando", "a_caminho", "entregue", "cancelado"] | None = None
    delivery_address: str | None = None
    delivery_driver_name: str | None = None
    notes: str | None = None


class DeliveryStatusUpdate(BaseModel):
    delivery_status: Literal["preparando", "a_caminho", "entregue", "cancelado"]
    payment_status: Literal["pago", "pendente"] | None = None
    delivery_driver_name: str | None = None


class DeliveryNotifyRequest(BaseModel):
    custom_message: str | None = None


class DeliveryResponse(DeliveryBase):
    id: int
    order_code: str
    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None
    customer_notified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Dados adicionais para renderização facilitada no frontend
    user_name: str | None = None
    user_phone: str | None = None
    user_whatsapp: str | None = None
    branch_name: str | None = None
    seller_name: str | None = None
    whatsapp_direct_url: str | None = None

    model_config = ConfigDict(from_attributes=True)
