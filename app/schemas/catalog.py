from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ProductSort(StrEnum):
    DEFAULT = "default"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    NAME_ASC = "name_asc"


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    name: str
    description: str
    price: Decimal
    image: str | None
    stock: int
    is_active: bool
    category: CategoryOut | None = None


class ProductListResponse(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    per_page: int
    pages: int
