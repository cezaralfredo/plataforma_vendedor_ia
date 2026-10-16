from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BranchBase(BaseModel):
    name: str = Field(..., max_length=100, description="Nome da loja / filial")
    code: str = Field(..., max_length=30, description="Código de identificação único da filial")
    cnpj: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)
    whatsapp_number: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=255)
    postal_code: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=255)
    address_number: str | None = Field(None, max_length=30)
    neighborhood: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=2)
    active: bool = True


class BranchCreate(BranchBase):
    pass


class BranchUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    code: str | None = Field(None, max_length=30)
    cnpj: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)
    whatsapp_number: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=255)
    postal_code: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=255)
    address_number: str | None = Field(None, max_length=30)
    neighborhood: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=2)
    active: bool | None = None


class BranchResponse(BranchBase):
    id: int
    created_at: datetime
    updated_at: datetime
    sellers_count: int = 0
    active_sellers_count: int = 0
    full_address: str | None = None

    model_config = ConfigDict(from_attributes=True)

