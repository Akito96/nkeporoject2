from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class RevenueByDayItem(BaseModel):
    day: date
    revenue: Decimal
    orders_count: int


class TopProductItem(BaseModel):
    product_id: int
    product_name: str
    quantity_sold: int
    revenue: Decimal


class OrdersByStatusItem(BaseModel):
    status: str
    orders_count: int
    revenue: Decimal


class RevenueByCategoryItem(BaseModel):
    category_id: int
    category_name: str
    quantity_sold: int
    revenue: Decimal


class StatsOverview(BaseModel):
    date_from: date
    date_to: date
    total_revenue: Decimal
    total_orders: int
    paid_or_active_orders: int
    average_check: Decimal
    revenue_by_day: list[RevenueByDayItem]
    top_products: list[TopProductItem]
    orders_by_status: list[OrdersByStatusItem]
    revenue_by_category: list[RevenueByCategoryItem]
