from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cart import Cart, CartItem
from app.models.catalog import Product
from app.schemas.cart import CartItemOut, CartOut


class CartProductNotFoundError(Exception):
    """Товар не найден или снят с продажи."""


class InsufficientStockError(Exception):
    """Недостаточно товара на складе."""


class CartItemNotFoundError(Exception):
    """Позиция отсутствует в корзине."""


async def get_or_create_cart(session: AsyncSession, user_id: int) -> Cart:
    cart = await session.scalar(
        select(Cart)
        .options(selectinload(Cart.items).selectinload(CartItem.product))
        .where(Cart.user_id == user_id)
    )
    if cart is None:
        cart = Cart(user_id=user_id)
        session.add(cart)
        await session.flush()
        # Повторно загружаем с пустой коллекцией items, чтобы избежать ленивой загрузки в async
        cart = await session.scalar(
            select(Cart)
            .options(selectinload(Cart.items).selectinload(CartItem.product))
            .where(Cart.id == cart.id)
        )
        assert cart is not None
    return cart


def serialize_cart(cart: Cart) -> CartOut:
    items_out: list[CartItemOut] = []
    total = Decimal("0.00")
    total_items = 0

    for item in sorted(cart.items, key=lambda x: x.id or 0):
        product = item.product
        subtotal = (product.price * item.quantity).quantize(Decimal("0.01"))
        total += subtotal
        total_items += item.quantity
        items_out.append(
            CartItemOut(
                product_id=product.id,
                name=product.name,
                price=product.price,
                image=product.image,
                stock=product.stock,
                quantity=item.quantity,
                subtotal=subtotal,
            )
        )

    return CartOut(
        items=items_out,
        total_items=total_items,
        total=total.quantize(Decimal("0.01")),
    )


async def get_cart_summary(session: AsyncSession, user_id: int) -> CartOut:
    cart = await get_or_create_cart(session, user_id)
    await session.commit()
    return serialize_cart(cart)


async def add_to_cart(
    session: AsyncSession,
    user_id: int,
    product_id: int,
    quantity: int,
) -> CartOut:
    product = await session.scalar(
        select(Product).where(Product.id == product_id, Product.is_active.is_(True))
    )
    if product is None:
        raise CartProductNotFoundError("Товар не найден или недоступен")

    cart = await get_or_create_cart(session, user_id)
    existing_item = next((i for i in cart.items if i.product_id == product_id), None)
    new_quantity = (existing_item.quantity if existing_item else 0) + quantity

    if new_quantity > product.stock:
        raise InsufficientStockError(
            f"Недостаточно товара «{product.name}»: доступно {product.stock} шт."
        )

    if existing_item is not None:
        existing_item.quantity = new_quantity
    else:
        cart.items.append(
            CartItem(
                cart_id=cart.id,
                product_id=product.id,
                quantity=new_quantity,
                product=product,
            )
        )

    await session.commit()
    return serialize_cart(cart)


async def update_cart_item(
    session: AsyncSession,
    user_id: int,
    product_id: int,
    quantity: int,
) -> CartOut:
    cart = await get_or_create_cart(session, user_id)
    existing_item = next((i for i in cart.items if i.product_id == product_id), None)
    if existing_item is None:
        raise CartItemNotFoundError("Товар не найден в корзине")

    if quantity == 0:
        cart.items.remove(existing_item)
        await session.commit()
        return serialize_cart(cart)

    product = existing_item.product
    if not product.is_active:
        raise CartProductNotFoundError(f"Товар «{product.name}» больше недоступен")

    if quantity > product.stock:
        raise InsufficientStockError(
            f"Недостаточно товара «{product.name}»: доступно {product.stock} шт."
        )

    existing_item.quantity = quantity
    await session.commit()
    return serialize_cart(cart)


async def remove_cart_item(
    session: AsyncSession,
    user_id: int,
    product_id: int,
) -> CartOut:
    cart = await get_or_create_cart(session, user_id)
    existing_item = next((i for i in cart.items if i.product_id == product_id), None)
    if existing_item is None:
        raise CartItemNotFoundError("Товар не найден в корзине")

    cart.items.remove(existing_item)
    await session.commit()
    return serialize_cart(cart)


async def clear_cart(session: AsyncSession, user_id: int) -> CartOut:
    cart = await get_or_create_cart(session, user_id)
    cart.items.clear()
    await session.commit()
    return serialize_cart(cart)
