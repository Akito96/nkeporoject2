from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.blog import Post
from app.models.catalog import Category, Product
from app.models.order import Order, OrderItem, OrderStatus
from app.schemas.admin import (
    AdminDashboardStats,
    AdminOrderOut,
    CategoryCreate,
    CategoryUpdate,
    ProductCreate,
    ProductUpdate,
)
from app.schemas.catalog import CategoryOut, ProductOut
from app.services.blog import slugify_title
from app.services.orders import ALLOWED_STATUS_TRANSITIONS, serialize_order


class AdminConflictError(Exception):
    """Конфликт уникальности или ссылочной целостности."""


class AdminNotFoundError(Exception):
    """Запрашиваемая сущность не найдена."""


async def get_dashboard_stats(session: AsyncSession) -> AdminDashboardStats:
    products_count = int(await session.scalar(select(func.count(Product.id))) or 0)
    categories_count = int(await session.scalar(select(func.count(Category.id))) or 0)
    orders_count = int(await session.scalar(select(func.count(Order.id))) or 0)
    posts_count = int(await session.scalar(select(func.count(Post.id))) or 0)
    return AdminDashboardStats(
        products_count=products_count,
        categories_count=categories_count,
        orders_count=orders_count,
        posts_count=posts_count,
    )


async def list_all_categories(session: AsyncSession) -> list[CategoryOut]:
    result = await session.scalars(select(Category).order_by(Category.name.asc()))
    return [CategoryOut.model_validate(c) for c in result.all()]


async def create_category(session: AsyncSession, payload: CategoryCreate) -> CategoryOut:
    slug = payload.slug or slugify_title(payload.name)
    dup_slug = await session.scalar(select(Category).where(Category.slug == slug))
    if dup_slug is not None:
        raise AdminConflictError(f"Категория со slug «{slug}» уже существует")

    dup_name = await session.scalar(select(Category).where(Category.name == payload.name))
    if dup_name is not None:
        raise AdminConflictError(f"Категория с названием «{payload.name}» уже существует")

    category = Category(name=payload.name, slug=slug)
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return CategoryOut.model_validate(category)


async def update_category(
    session: AsyncSession,
    category_id: int,
    payload: CategoryUpdate,
) -> CategoryOut:
    category = await session.scalar(select(Category).where(Category.id == category_id))
    if category is None:
        raise AdminNotFoundError("Категория не найдена")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None and updates["name"] != category.name:
        dup_name = await session.scalar(select(Category).where(Category.name == updates["name"]))
        if dup_name is not None:
            raise AdminConflictError(f"Категория с названием «{updates['name']}» уже существует")
        category.name = updates["name"]

    if "slug" in updates and updates["slug"] is not None and updates["slug"] != category.slug:
        dup_slug = await session.scalar(select(Category).where(Category.slug == updates["slug"]))
        if dup_slug is not None:
            raise AdminConflictError(f"Категория со slug «{updates['slug']}» уже существует")
        category.slug = updates["slug"]

    await session.commit()
    await session.refresh(category)
    return CategoryOut.model_validate(category)


async def delete_category(session: AsyncSession, category_id: int) -> None:
    category = await session.scalar(select(Category).where(Category.id == category_id))
    if category is None:
        raise AdminNotFoundError("Категория не найдена")

    linked_products = int(
        await session.scalar(
            select(func.count(Product.id)).where(Product.category_id == category_id)
        )
        or 0
    )
    if linked_products > 0:
        raise AdminConflictError(
            "Нельзя удалить категорию, пока в ней есть товары. Сначала перенесите или удалите их."
        )

    await session.delete(category)
    await session.commit()


async def list_all_products(session: AsyncSession) -> list[ProductOut]:
    result = await session.scalars(
        select(Product).options(selectinload(Product.category)).order_by(Product.id.desc())
    )
    return [ProductOut.model_validate(p) for p in result.all()]


async def create_product(session: AsyncSession, payload: ProductCreate) -> ProductOut:
    category = await session.scalar(
        select(Category).where(Category.id == payload.category_id)
    )
    if category is None:
        raise AdminNotFoundError("Выбранная категория не найдена")

    product = Product(
        category_id=payload.category_id,
        name=payload.name,
        description=payload.description,
        price=payload.price,
        image=payload.image,
        stock=payload.stock,
        is_active=payload.is_active,
        category=category,
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return ProductOut.model_validate(product)


async def update_product(
    session: AsyncSession,
    product_id: int,
    payload: ProductUpdate,
) -> ProductOut:
    product = await session.scalar(
        select(Product).options(selectinload(Product.category)).where(Product.id == product_id)
    )
    if product is None:
        raise AdminNotFoundError("Товар не найден")

    updates = payload.model_dump(exclude_unset=True)
    if "category_id" in updates and updates["category_id"] is not None:
        category = await session.scalar(
            select(Category).where(Category.id == updates["category_id"])
        )
        if category is None:
            raise AdminNotFoundError("Выбранная категория не найдена")
        product.category_id = category.id
        product.category = category

    for field in ("name", "description", "price", "image", "stock", "is_active"):
        if field in updates:
            setattr(product, field, updates[field])

    await session.commit()
    await session.refresh(product)
    return ProductOut.model_validate(product)


async def delete_product(session: AsyncSession, product_id: int) -> None:
    product = await session.scalar(select(Product).where(Product.id == product_id))
    if product is None:
        raise AdminNotFoundError("Товар не найден")

    ordered_count = int(
        await session.scalar(
            select(func.count(OrderItem.id)).where(OrderItem.product_id == product_id)
        )
        or 0
    )
    if ordered_count > 0:
        raise AdminConflictError(
            "Товар участвует в оформленных заказах. Скройте его, отключив флаг «Активен»."
        )

    await session.delete(product)
    await session.commit()


async def list_all_orders(
    session: AsyncSession,
    *,
    status_filter: OrderStatus | None = None,
    limit: int = 100,
) -> list[AdminOrderOut]:
    query = (
        select(Order)
        .options(
            selectinload(Order.user),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
    if status_filter is not None:
        query = query.where(Order.status == status_filter.value)

    result = await session.scalars(query)
    orders_out: list[AdminOrderOut] = []
    for order in result.all():
        serialized = serialize_order(order)
        current_status = OrderStatus(order.status)
        orders_out.append(
            AdminOrderOut(
                id=serialized.id,
                user_id=serialized.user_id,
                user_email=order.user.email if order.user else f"user#{order.user_id}",
                status=serialized.status,
                total=serialized.total,
                created_at=serialized.created_at,
                items=serialized.items,
                allowed_next_statuses=sorted(
                    ALLOWED_STATUS_TRANSITIONS[current_status],
                    key=lambda s: s.value,
                ),
            )
        )
    return orders_out
