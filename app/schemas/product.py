from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_product_image_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.startswith(("https://", "http://", "/admin/static/uploads/products/")):
        return cleaned
    raise ValueError(
        "URL da imagem deve iniciar com https://, http:// ou /admin/static/uploads/products/"
    )


class ProductBase(BaseModel):
    name: str = Field(..., max_length=255, description="Nome do produto")
    description: str | None = Field(default=None, description="Descrição detalhada do produto")
    category: str | None = Field(default=None, max_length=100, description="Categoria do produto")
    price_cents: int = Field(..., ge=0, description="Preço do produto em centavos")
    stock_quantity: int = Field(default=0, ge=0, description="Quantidade disponível em estoque")
    weight_kg: Decimal | None = Field(
        default=None, ge=0, description="Peso do produto em quilogramas (ex: 0.350)"
    )
    sku: str | None = Field(default=None, max_length=50, description="Código de referência/SKU")
    image_url: str | None = Field(default=None, max_length=500, description="URL da foto do produto")
    active: bool = Field(default=True, description="Indica se o produto está visível para venda")

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        return _validate_product_image_url(value)


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    category: str | None = Field(default=None, max_length=100)
    price_cents: int | None = Field(default=None, ge=0)
    stock_quantity: int | None = Field(default=None, ge=0)
    weight_kg: Decimal | None = Field(default=None, ge=0)
    sku: str | None = Field(default=None, max_length=50)
    image_url: str | None = Field(default=None, max_length=500)
    active: bool | None = None

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        return _validate_product_image_url(value)


class ProductResponse(ProductBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


ProductRead = ProductResponse

