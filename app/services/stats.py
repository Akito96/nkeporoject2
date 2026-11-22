import csv
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Category, Product
from app.models.order import Order, OrderItem, OrderStatus
from app.schemas.stats import (
    OrdersByStatusItem,
    RevenueByCategoryItem,
    RevenueByDayItem,
    StatsOverview,
    TopProductItem,
)


class InvalidDateRangeError(Exception):
    """Некорректный диапазон дат для аналитики."""


def resolve_date_range(
    *,
    days: int = 30,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[date, date, datetime, datetime]:
    """Преобразует параметры периода в границы [start_dt, end_dt) в UTC."""
    today = datetime.now(UTC).date()
    resolved_to = date_to or today
    resolved_from = date_from or (resolved_to - timedelta(days=days - 1))

    if resolved_from > resolved_to:
        raise InvalidDateRangeError("Дата начала периода не может быть позже даты окончания")
    if (resolved_to - resolved_from).days > 366:
        raise InvalidDateRangeError("Максимальный диапазон аналитики — 366 дней")

    start_dt = datetime.combine(resolved_from, time.min, tzinfo=UTC)
    end_dt = datetime.combine(resolved_to + timedelta(days=1), time.min, tzinfo=UTC)
    return resolved_from, resolved_to, start_dt, end_dt


def _to_money(value: Decimal | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def get_revenue_by_day(
    session: AsyncSession,
    start_dt: datetime,
    end_dt: datetime,
) -> list[RevenueByDayItem]:
    day_col = cast(func.date_trunc("day", Order.created_at), Date).label("day")
    stmt = (
        select(
            day_col,
            func.coalesce(func.sum(Order.total), 0).label("revenue"),
            func.count(Order.id).label("orders_count"),
        )
        .where(
            Order.created_at >= start_dt,
            Order.created_at < end_dt,
            Order.status != OrderStatus.CANCELLED.value,
        )
        .group_by(day_col)
        .order_by(day_col.asc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        RevenueByDayItem(
            day=row.day,
            revenue=_to_money(row.revenue),
            orders_count=int(row.orders_count),
        )
        for row in rows
    ]


async def get_top_products(
    session: AsyncSession,
    start_dt: datetime,
    end_dt: datetime,
    *,
    limit: int = 10,
) -> list[TopProductItem]:
    revenue_expr = func.coalesce(func.sum(OrderItem.price * OrderItem.quantity), 0).label("revenue")
    qty_expr = func.coalesce(func.sum(OrderItem.quantity), 0).label("quantity_sold")

    stmt = (
        select(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            qty_expr,
            revenue_expr,
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.created_at >= start_dt,
            Order.created_at < end_dt,
            Order.status != OrderStatus.CANCELLED.value,
        )
        .group_by(Product.id, Product.name)
        .order_by(revenue_expr.desc(), qty_expr.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        TopProductItem(
            product_id=int(row.product_id),
            product_name=str(row.product_name),
            quantity_sold=int(row.quantity_sold),
            revenue=_to_money(row.revenue),
        )
        for row in rows
    ]


async def get_orders_by_status(
    session: AsyncSession,
    start_dt: datetime,
    end_dt: datetime,
) -> list[OrdersByStatusItem]:
    stmt = (
        select(
            Order.status.label("status"),
            func.count(Order.id).label("orders_count"),
            func.coalesce(func.sum(Order.total), 0).label("revenue"),
        )
        .where(
            Order.created_at >= start_dt,
            Order.created_at < end_dt,
        )
        .group_by(Order.status)
        .order_by(Order.status.asc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        OrdersByStatusItem(
            status=str(row.status),
            orders_count=int(row.orders_count),
            revenue=_to_money(row.revenue),
        )
        for row in rows
    ]


async def get_revenue_by_category(
    session: AsyncSession,
    start_dt: datetime,
    end_dt: datetime,
) -> list[RevenueByCategoryItem]:
    revenue_expr = func.coalesce(func.sum(OrderItem.price * OrderItem.quantity), 0).label("revenue")
    qty_expr = func.coalesce(func.sum(OrderItem.quantity), 0).label("quantity_sold")

    stmt = (
        select(
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            qty_expr,
            revenue_expr,
        )
        .join(Product, Product.category_id == Category.id)
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.created_at >= start_dt,
            Order.created_at < end_dt,
            Order.status != OrderStatus.CANCELLED.value,
        )
        .group_by(Category.id, Category.name)
        .order_by(revenue_expr.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        RevenueByCategoryItem(
            category_id=int(row.category_id),
            category_name=str(row.category_name),
            quantity_sold=int(row.quantity_sold),
            revenue=_to_money(row.revenue),
        )
        for row in rows
    ]


async def get_average_check_and_totals(
    session: AsyncSession,
    start_dt: datetime,
    end_dt: datetime,
) -> tuple[Decimal, int, Decimal]:
    """Возвращает (выручка, кол-во не отменённых заказов, средний чек)."""
    stmt = select(
        func.coalesce(func.sum(Order.total), 0).label("total_revenue"),
        func.count(Order.id).label("orders_count"),
        func.coalesce(func.avg(Order.total), 0).label("avg_check"),
    ).where(
        Order.created_at >= start_dt,
        Order.created_at < end_dt,
        Order.status != OrderStatus.CANCELLED.value,
    )
    row = (await session.execute(stmt)).one()
    return (
        _to_money(row.total_revenue),
        int(row.orders_count),
        _to_money(row.avg_check),
    )


async def get_stats_overview(
    session: AsyncSession,
    *,
    days: int = 30,
    date_from: date | None = None,
    date_to: date | None = None,
) -> StatsOverview:
    d_from, d_to, start_dt, end_dt = resolve_date_range(
        days=days,
        date_from=date_from,
        date_to=date_to,
    )
    total_revenue, active_orders, avg_check = await get_average_check_and_totals(
        session, start_dt, end_dt
    )
    revenue_by_day = await get_revenue_by_day(session, start_dt, end_dt)
    top_products = await get_top_products(session, start_dt, end_dt)
    orders_by_status = await get_orders_by_status(session, start_dt, end_dt)
    revenue_by_category = await get_revenue_by_category(session, start_dt, end_dt)

    total_orders = sum(item.orders_count for item in orders_by_status)
    return StatsOverview(
        date_from=d_from,
        date_to=d_to,
        total_revenue=total_revenue,
        total_orders=total_orders,
        paid_or_active_orders=active_orders,
        average_check=avg_check,
        revenue_by_day=revenue_by_day,
        top_products=top_products,
        orders_by_status=orders_by_status,
        revenue_by_category=revenue_by_category,
    )


def build_stats_csv(overview: StatsOverview) -> str:
    """Формирует CSV-отчёт с UTF-8 BOM для корректного открытия кириллицы в Excel."""
    buffer = StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, delimiter=";")

    writer.writerow(["Отчёт по продажам кофейни", f"{overview.date_from} — {overview.date_to}"])
    writer.writerow(["Выручка (₽)", f"{overview.total_revenue:.2f}"])
    writer.writerow(["Всего заказов", overview.total_orders])
    writer.writerow(["Средний чек (₽)", f"{overview.average_check:.2f}"])
    writer.writerow([])

    writer.writerow(["Выручка по дням"])
    writer.writerow(["Дата", "Заказов", "Выручка (₽)"])
    for day_item in overview.revenue_by_day:
        writer.writerow(
            [day_item.day.isoformat(), day_item.orders_count, f"{day_item.revenue:.2f}"]
        )
    writer.writerow([])

    writer.writerow(["Топ-10 товаров"])
    writer.writerow(["Товар", "Продано шт.", "Выручка (₽)"])
    for prod in overview.top_products:
        writer.writerow([prod.product_name, prod.quantity_sold, f"{prod.revenue:.2f}"])
    writer.writerow([])

    writer.writerow(["Выручка по категориям"])
    writer.writerow(["Категория", "Продано шт.", "Выручка (₽)"])
    for cat in overview.revenue_by_category:
        writer.writerow([cat.category_name, cat.quantity_sold, f"{cat.revenue:.2f}"])
    writer.writerow([])

    writer.writerow(["Заказы по статусам"])
    writer.writerow(["Статус", "Количество", "Сумма (₽)"])
    for st in overview.orders_by_status:
        writer.writerow([st.status, st.orders_count, f"{st.revenue:.2f}"])

    return buffer.getvalue()
