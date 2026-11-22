from math import ceil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Category, Product
from app.schemas.catalog import ProductSort


async def list_categories(session: AsyncSession) -> list[Category]:
    result = await session.scalars(select(Category).order_by(Category.name.asc()))
    return list(result.all())


async def list_products(
    session: AsyncSession,
    *,
    category_slug: str | None = None,
    search: str | None = None,
    sort: ProductSort = ProductSort.DEFAULT,
    page: int = 1,
    per_page: int = 12,
    active_only: bool = True,
) -> tuple[list[Product], int]:
    """Возвращает страницу товаров с фильтрацией, поиском, сортировкой и общим количеством."""
    query = select(Product).options(selectinload(Product.category))
    count_query = select(func.count(Product.id))

    if active_only:
        query = query.where(Product.is_active.is_(True))
        count_query = count_query.where(Product.is_active.is_(True))

    if category_slug:
        normalized_slug = category_slug.strip().lower()
        query = query.join(Product.category).where(Category.slug == normalized_slug)
        count_query = count_query.join(Product.category).where(Category.slug == normalized_slug)

    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.where(Product.name.ilike(pattern))
        count_query = count_query.where(Product.name.ilike(pattern))

    if sort == ProductSort.PRICE_ASC:
        query = query.order_by(Product.price.asc(), Product.id.asc())
    elif sort == ProductSort.PRICE_DESC:
        query = query.order_by(Product.price.desc(), Product.id.asc())
    elif sort == ProductSort.NAME_ASC:
        query = query.order_by(Product.name.asc(), Product.id.asc())
    else:
        query = query.order_by(Product.id.asc())

    total = int(await session.scalar(count_query) or 0)
    offset = (page - 1) * per_page
    result = await session.scalars(query.offset(offset).limit(per_page))
    return list(result.all()), total


def calculate_total_pages(total: int, per_page: int) -> int:
    if total <= 0:
        return 1
    return ceil(total / per_page)


async def get_product_by_id(
    session: AsyncSession,
    product_id: int,
    *,
    active_only: bool = True,
) -> Product | None:
    query = (
        select(Product)
        .options(selectinload(Product.category))
        .where(Product.id == product_id)
    )
    if active_only:
        query = query.where(Product.is_active.is_(True))
    return await session.scalar(query)
