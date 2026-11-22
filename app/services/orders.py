from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cart import Cart
from app.models.catalog import Product
from app.models.order import Order, OrderItem, OrderStatus
from app.schemas.orders import OrderItemOut, OrderOut
from app.services.cart import InsufficientStockError


class EmptyCartError(Exception):
    """Нельзя оформить заказ из пустой корзины."""


class OrderNotFoundError(Exception):
    """Заказ не найден."""


class InvalidOrderStatusTransitionError(Exception):
    """Недопустимый переход статуса заказа."""


ALLOWED_STATUS_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.DONE, OrderStatus.CANCELLED},
    OrderStatus.DONE: set(),
    OrderStatus.CANCELLED: set(),
}


def serialize_order(order: Order) -> OrderOut:
    items_out: list[OrderItemOut] = []
    for item in sorted(order.items, key=lambda x: x.id or 0):
        product_name = item.product.name if item.product else f"Товар #{item.product_id}"
        subtotal = (item.price * item.quantity).quantize(Decimal("0.01"))
        items_out.append(
            OrderItemOut(
                id=item.id,
                product_id=item.product_id,
                product_name=product_name,
                quantity=item.quantity,
                price=item.price,
                subtotal=subtotal,
            )
        )

    return OrderOut(
        id=order.id,
        user_id=order.user_id,
        status=OrderStatus(order.status),
        total=order.total,
        created_at=order.created_at,
        items=items_out,
    )


async def create_order_from_cart(session: AsyncSession, user_id: int) -> OrderOut:
    """Создаёт заказ из корзины в одной транзакции: проверяет остатки, фиксирует цены, чистит."""
    try:
        cart = await session.scalar(
            select(Cart)
            .options(selectinload(Cart.items))
            .where(Cart.user_id == user_id)
        )
        if cart is None or not cart.items:
            raise EmptyCartError("Корзина пуста. Добавьте товары перед оформлением заказа.")

        product_ids = sorted({item.product_id for item in cart.items})
        # Блокируем строки товаров в детерминированном порядке по id, чтобы избежать deadlock
        locked_products_result = await session.scalars(
            select(Product)
            .where(Product.id.in_(product_ids))
            .order_by(Product.id.asc())
            .with_for_update()
        )
        products_by_id = {p.id: p for p in locked_products_result.all()}

        total = Decimal("0.00")
        order_items: list[OrderItem] = []

        for cart_item in cart.items:
            product = products_by_id.get(cart_item.product_id)
            if product is None or not product.is_active:
                raise InsufficientStockError(
                    f"Товар #{cart_item.product_id} больше недоступен для заказа"
                )
            if cart_item.quantity > product.stock:
                raise InsufficientStockError(
                    f"Недостаточно товара «{product.name}»: "
                    f"запрошено {cart_item.quantity}, доступно {product.stock}"
                )

            product.stock -= cart_item.quantity
            line_total = (product.price * cart_item.quantity).quantize(Decimal("0.01"))
            total += line_total
            order_items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=cart_item.quantity,
                    price=product.price,
                    product=product,
                )
            )

        order = Order(
            user_id=user_id,
            status=OrderStatus.NEW.value,
            total=total.quantize(Decimal("0.01")),
            items=order_items,
        )
        session.add(order)
        cart.items.clear()

        await session.commit()
        await session.refresh(order)
        return serialize_order(order)
    except Exception:
        await session.rollback()
        raise


async def list_user_orders(session: AsyncSession, user_id: int) -> list[OrderOut]:
    result = await session.scalars(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    return [serialize_order(order) for order in result.all()]


async def get_order_by_id(session: AsyncSession, order_id: int) -> Order | None:
    return await session.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .where(Order.id == order_id)
    )


async def update_order_status(
    session: AsyncSession,
    order_id: int,
    new_status: OrderStatus,
) -> OrderOut:
    order = await get_order_by_id(session, order_id)
    if order is None:
        raise OrderNotFoundError("Заказ не найден")

    current_status = OrderStatus(order.status)
    if new_status not in ALLOWED_STATUS_TRANSITIONS[current_status]:
        raise InvalidOrderStatusTransitionError(
            f"Нельзя перевести заказ из статуса «{current_status.value}» в «{new_status.value}»"
        )

    order.status = new_status.value

    # При отмене возвращаем товары обратно на склад
    if new_status == OrderStatus.CANCELLED:
        for item in order.items:
            if item.product is not None:
                item.product.stock += item.quantity

    await session.commit()
    await session.refresh(order)
    return serialize_order(order)
