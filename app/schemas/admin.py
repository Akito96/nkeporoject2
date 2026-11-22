import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.order import OrderStatus
from app.schemas.orders import OrderItemOut

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _clean_slug(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if len(normalized) > 120 or not SLUG_RE.match(normalized):
        raise ValueError("Slug может содержать только латинские буквы, цифры и дефисы")
    return normalized


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=120)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Название категории должно содержать минимум 2 символа")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        return _clean_slug(value)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=120)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Название категории должно содержать минимум 2 символа")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        return _clean_slug(value)


class ProductCreate(BaseModel):
    category_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)
    price: Decimal = Field(..., ge=Decimal("0.00"), max_digits=10, decimal_places=2)
    image: str | None = Field(default=None, max_length=500)
    stock: int = Field(default=0, ge=0)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Название товара должно содержать минимум 2 символа")
        return cleaned


class ProductUpdate(BaseModel):
    category_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal | None = Field(default=None, ge=Decimal("0.00"), max_digits=10, decimal_places=2)
    image: str | None = Field(default=None, max_length=500)
    stock: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Название товара должно содержать минимум 2 символа")
        return cleaned


class UploadImageOut(BaseModel):
    url: str
    filename: str
    size: int


class AdminOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_email: str
    status: OrderStatus
    total: Decimal
    created_at: datetime
    items: list[OrderItemOut]
    allowed_next_statuses: list[OrderStatus]


class AdminDashboardStats(BaseModel):
    products_count: int
    categories_count: int
    orders_count: int
    posts_count: int
