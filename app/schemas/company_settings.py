from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FinancialSettingsSchema(BaseModel):
    payment_required: bool = Field(
        default=True,
        description="Se verdadeiro, exige pagamento antecipado para confirmar a reserva. Se falso, confirma na hora.",
    )
    default_gateway: str = Field(
        default="asaas",
        description="Gateway padrão ('asaas', 'mercadopago', 'stripe', 'pix_direto', 'manual', 'none')",
    )
    gateway_credentials: dict[str, Any] = Field(
        default_factory=dict,
        description="Credenciais e tokens de acesso específicos do gateway",
    )
    accepted_payment_methods: list[str] = Field(
        default_factory=lambda: ["pix"],
        description="Métodos aceitos: pix, credit_card, boleto, in_person",
    )


class CommissionSettingsSchema(BaseModel):
    commission_model: str = Field(
        default="percentage",
        description="Modelo de comissão ('percentage', 'fixed_value', 'split_gateway', 'manual_settlement', 'none')",
    )
    default_commission_rate: Decimal = Field(
        default=Decimal("0.0"),
        description="Taxa percentual ou valor fixo padrão de comissão",
    )
    split_enabled: bool = Field(
        default=False,
        description="Se o gateway realiza split financeiro automático no ato da cobrança",
    )


class ChannelSettingsSchema(BaseModel):
    whatsapp_provider: str = Field(
        default="evolution",
        description="Provedor de WhatsApp ('evolution' ou 'meta')",
    )
    evolution_instance: str | None = Field(
        default=None,
        description="Nome da instância na Evolution API",
    )
    meta_phone_number_id: str | None = Field(
        default=None,
        description="ID do telefone na Meta Cloud API",
    )
    meta_access_token: str | None = Field(
        default=None,
        description="Token de acesso WABA na Meta",
    )
    meta_waba_id: str | None = Field(
        default=None,
        description="ID da conta WhatsApp Business (WABA)",
    )


class AIAttendanceSettingsSchema(BaseModel):
    company_name: str = Field(
        default="Minha Empresa",
        description="Nome da empresa apresentado no atendimento",
    )
    assistant_name: str = Field(
        default="Assistente",
        description="Nome da persona do assistente virtual",
    )
    tone: str = Field(
        default="casual",
        description="Tom da linguagem ('casual', 'formal', 'executive')",
    )
    require_cpf: bool = Field(
        default=False,
        description="Se exige CPF para criar o cadastro do cliente",
    )
    welcome_message: str | None = Field(
        default=None,
        description="Mensagem de boas-vindas customizada",
    )


class CompanySettingsCreate(BaseModel):
    company_name: str = "Minha Empresa"
    payment_required: bool = True
    default_gateway: str = "asaas"
    gateway_credentials: dict[str, Any] = Field(default_factory=dict)
    accepted_payment_methods: list[str] = Field(default_factory=lambda: ["pix"])
    commission_model: str = "percentage"
    default_commission_rate: Decimal = Decimal("0.0")
    split_enabled: bool = False
    whatsapp_provider: str = "evolution"
    evolution_instance: str | None = None
    meta_phone_number_id: str | None = None
    meta_access_token: str | None = None
    meta_waba_id: str | None = None
    assistant_name: str = "Assistente"
    tone: str = "casual"
    require_cpf: bool = False
    welcome_message: str | None = None
    custom_settings: dict[str, Any] = Field(default_factory=dict)


class CompanySettingsUpdate(BaseModel):
    company_name: str | None = None
    payment_required: bool | None = None
    default_gateway: str | None = None
    gateway_credentials: dict[str, Any] | None = None
    accepted_payment_methods: list[str] | None = None
    commission_model: str | None = None
    default_commission_rate: Decimal | None = None
    split_enabled: bool | None = None
    whatsapp_provider: str | None = None
    evolution_instance: str | None = None
    meta_phone_number_id: str | None = None
    meta_access_token: str | None = None
    meta_waba_id: str | None = None
    assistant_name: str | None = None
    tone: str | None = None
    require_cpf: bool | None = None
    welcome_message: str | None = None
    custom_settings: dict[str, Any] | None = None


class CompanySettingsResponse(BaseModel):
    id: int
    company_name: str
    payment_required: bool
    default_gateway: str
    gateway_credentials: dict[str, Any]
    accepted_payment_methods: list[str]
    commission_model: str
    default_commission_rate: Decimal
    split_enabled: bool
    whatsapp_provider: str
    evolution_instance: str | None
    meta_phone_number_id: str | None
    meta_access_token: str | None
    meta_waba_id: str | None
    assistant_name: str
    tone: str
    require_cpf: bool
    welcome_message: str | None
    custom_settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
