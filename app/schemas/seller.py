from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SellerBase(BaseModel):
    branch_id: int = Field(..., description="ID da filial à qual o vendedor pertence")
    name: str = Field(..., max_length=255, description="Nome completo do vendedor")
    email: str = Field(..., max_length=255, description="E-mail de acesso à Área de Vendas")

    phone: str | None = Field(None, max_length=20)
    whatsapp_number: str = Field(..., max_length=20, description="WhatsApp de atendimento do vendedor")
    cpf: str | None = Field(None, max_length=20)
    code: str = Field(..., max_length=30, description="Código de identificação único do vendedor")
    commission_rate: float = Field(0.0, ge=0.0, le=100.0, description="Percentual de comissão por venda (%)")
    pix_key: str | None = Field(None, max_length=100, description="Chave PIX do vendedor para repasse")
    active: bool = True


class SellerCreate(SellerBase):
    password: str = Field(..., min_length=6, description="Senha de acesso à Área de Vendas")


class SellerUpdate(BaseModel):
    branch_id: int | None = None
    name: str | None = Field(None, max_length=255)
    email: str | None = None
    phone: str | None = Field(None, max_length=20)
    whatsapp_number: str | None = Field(None, max_length=20)
    cpf: str | None = Field(None, max_length=20)
    code: str | None = Field(None, max_length=30)
    commission_rate: float | None = Field(None, ge=0.0, le=100.0)
    pix_key: str | None = Field(None, max_length=100)
    active: bool | None = None
    password: str | None = Field(None, min_length=6)


class SellerResponse(SellerBase):
    id: int
    branch_name: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SellerLoginRequest(BaseModel):
    email: str
    password: str



class SellerMetricsResponse(BaseModel):
    seller_id: int
    seller_name: str
    branch_name: str
    total_sales_cents: int
    total_orders_count: int
    total_commission_cents: int
    paid_commission_cents: int
    pending_commission_cents: int
