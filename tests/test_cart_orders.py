from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import create_app
from app.models.cart import Cart
from app.models.catalog import Category, Product
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password


class _ScalarList:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class InMemoryShopSession:
    """In-memory async-сессия для сквозных тестов корзины и заказов без внешней БД."""

    def __init__(
        self,
        users: list[User],
        products: list[Product],
    ) -> None:
        self.users = list(users)
        self.products = list(products)
        self.carts: list[Cart] = []
        self.orders: list[Order] = []
        self._next_cart_id = 1
        self._next_cart_item_id = 1
        self._next_order_id = 1
        self._next_order_item_id = 1
        self._stock_snapshot: dict[int, int] = {}

    def _snapshot_stock(self) -> None:
        self._stock_snapshot = {p.id: p.stock for p in self.products}

    async def scalar(self, stmt: Any) -> Any:
        compiled = stmt.compile()
        sql = str(compiled)
        params = compiled.params

        if "FROM users" in sql:
            if "id_1" in params:
                return next((u for u in self.users if u.id == params["id_1"]), None)
            if "email_1" in params:
                return next((u for u in self.users if u.email == params["email_1"]), None)

        if "FROM products" in sql:
            pid = params.get("id_1")
            for p in self.products:
                if p.id == pid and ("is_active IS true" not in sql or p.is_active):
                    return p
            return None

        if "FROM carts" in sql:
            if "user_id_1" in params:
                uid = params["user_id_1"]
                return next((c for c in self.carts if c.user_id == uid), None)
            if "id_1" in params:
                cid = params["id_1"]
                return next((c for c in self.carts if c.id == cid), None)

        if "FROM orders" in sql:
            oid = params.get("id_1")
            return next((o for o in self.orders if o.id == oid), None)

        return None

    async def scalars(self, stmt: Any) -> _ScalarList:
        compiled = stmt.compile()
        sql = str(compiled)
        params = compiled.params

        if "FROM products" in sql:
            self._snapshot_stock()
            ids = set(params.get("id_1", []))
            matched = sorted(
                (p for p in self.products if p.id in ids),
                key=lambda p: p.id,
            )
            return _ScalarList(matched)

        if "FROM orders" in sql:
            uid = params.get("user_id_1")
            matched = [o for o in self.orders if o.user_id == uid]
            matched.sort(key=lambda o: (o.created_at, o.id), reverse=True)
            return _ScalarList(matched)

        return _ScalarList([])

    def add(self, obj: Any) -> None:
        if isinstance(obj, Cart):
            if getattr(obj, "id", None) is None:
                obj.id = self._next_cart_id
                self._next_cart_id += 1
            if not hasattr(obj, "items") or obj.items is None:
                obj.items = []
            self.carts.append(obj)
        elif isinstance(obj, Order):
            if getattr(obj, "id", None) is None:
                obj.id = self._next_order_id
                self._next_order_id += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)
            for item in obj.items:
                if getattr(item, "id", None) is None:
                    item.id = self._next_order_item_id
                    self._next_order_item_id += 1
                item.order_id = obj.id
            self.orders.append(obj)

    async def flush(self) -> None:
        for cart in self.carts:
            for item in cart.items:
                if getattr(item, "id", None) is None:
                    item.id = self._next_cart_item_id
                    self._next_cart_item_id += 1

    async def commit(self) -> None:
        await self.flush()
        self._stock_snapshot = {}

    async def rollback(self) -> None:
        # Откатываем изменения остатков при ошибке внутри транзакции оформления заказа
        for p in self.products:
            if p.id in self._stock_snapshot:
                p.stock = self._stock_snapshot[p.id]
        self._stock_snapshot = {}

    async def refresh(self, _obj: Any) -> None:
        return None


def _make_fixture() -> tuple[FastAPI, InMemoryShopSession, User, User, User, list[Product]]:
    user1 = User(
        id=1,
        email="guest@coffee.local",
        password_hash=hash_password("GuestPass123"),
        role=UserRole.USER.value,
        created_at=datetime.now(UTC),
    )
    user2 = User(
        id=2,
        email="other@coffee.local",
        password_hash=hash_password("OtherPass123"),
        role=UserRole.USER.value,
        created_at=datetime.now(UTC),
    )
    admin = User(
        id=3,
        email="admin@coffee.local",
        password_hash=hash_password("AdminPass123"),
        role=UserRole.ADMIN.value,
        created_at=datetime.now(UTC),
    )
    cat = Category(id=1, name="Кофе", slug="coffee")
    products = [
        Product(
            id=1,
            category_id=1,
            name="Капучино",
            description="Классический капучино",
            price=Decimal("260.00"),
            image=None,
            stock=5,
            is_active=True,
            category=cat,
        ),
        Product(
            id=2,
            category_id=1,
            name="Круассан",
            description="Миндальный круассан",
            price=Decimal("270.00"),
            image=None,
            stock=2,
            is_active=True,
            category=cat,
        ),
    ]

    session = InMemoryShopSession([user1, user2, admin], products)
    app = create_app()

    async def override_get_db() -> AsyncGenerator[InMemoryShopSession, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return app, session, user1, user2, admin, products


def _auth_cookie(user: User) -> dict[str, str]:
    return {"access_token": create_access_token(user.id, user.role)}


@pytest.mark.asyncio
async def test_cart_crud_and_stock_limits() -> None:
    app, _, user1, _, _, _ = _make_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Без авторизации -> 401
        assert (await client.get("/cart")).status_code == 401

        client.cookies.update(_auth_cookie(user1))

        # Добавление товара
        r1 = await client.post("/cart/items", json={"product_id": 1, "quantity": 2})
        assert r1.status_code == 200
        assert r1.json()["total_items"] == 2
        assert Decimal(r1.json()["total"]) == Decimal("520.00")

        # Превышение остатка (stock=5, уже 2, просим +4) -> 409
        r_over = await client.post("/cart/items", json={"product_id": 1, "quantity": 4})
        assert r_over.status_code == 409

        # Изменение количества
        r_upd = await client.patch("/cart/items/1", json={"quantity": 3})
        assert r_upd.status_code == 200
        assert Decimal(r_upd.json()["total"]) == Decimal("780.00")

        # Добавление второго товара и удаление первого
        await client.post("/cart/items", json={"product_id": 2, "quantity": 1})
        r_del = await client.delete("/cart/items/1")
        assert r_del.status_code == 200
        assert len(r_del.json()["items"]) == 1

        # Очистка корзины
        r_clear = await client.delete("/cart")
        assert r_clear.status_code == 200
        assert r_clear.json()["items"] == []
        assert Decimal(r_clear.json()["total"]) == Decimal("0.00")


@pytest.mark.asyncio
async def test_checkout_empty_cart_returns_400() -> None:
    app, _, user1, _, _, _ = _make_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=_auth_cookie(user1),
    ) as client:
        resp = await client.post("/orders")
        assert resp.status_code == 400
        assert "пуста" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_checkout_insufficient_stock_rolls_back() -> None:
    app, session, user1, _, _, products = _make_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=_auth_cookie(user1),
    ) as client:
        await client.post("/cart/items", json={"product_id": 1, "quantity": 2})
        await client.post("/cart/items", json={"product_id": 2, "quantity": 2})

        # Имитируем, что пока пользователь оформлял заказ, товар #2 раскупили
        products[1].stock = 1

        resp = await client.post("/orders")
        assert resp.status_code == 409
        assert "Недостаточно товара" in resp.json()["detail"]

        # Откат транзакции: остаток товара #1 не списан, заказ не создан, корзина цела
        assert products[0].stock == 5
        assert len(session.orders) == 0
        cart_resp = await client.get("/cart")
        assert cart_resp.json()["total_items"] == 4


@pytest.mark.asyncio
async def test_checkout_freezes_price_decrements_stock_and_clears_cart() -> None:
    app, _, user1, user2, admin, products = _make_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=_auth_cookie(user1),
    ) as client:
        await client.post("/cart/items", json={"product_id": 1, "quantity": 2})

        order_resp = await client.post("/orders")
        assert order_resp.status_code == 201
        order_data = order_resp.json()
        assert order_data["status"] == OrderStatus.NEW.value
        assert Decimal(order_data["total"]) == Decimal("520.00")
        assert Decimal(order_data["items"][0]["price"]) == Decimal("260.00")

        # Остаток списан, корзина очищена
        assert products[0].stock == 3
        assert (await client.get("/cart")).json()["items"] == []

        # Меняем цену товара в каталоге — в истории заказа остаётся цена на момент покупки
        products[0].price = Decimal("310.00")
        detail = await client.get(f"/orders/{order_data['id']}")
        assert detail.status_code == 200
        assert Decimal(detail.json()["items"][0]["price"]) == Decimal("260.00")

        # Чужой пользователь не имеет доступа -> 403
        client.cookies.update(_auth_cookie(user2))
        forbidden = await client.get(f"/orders/{order_data['id']}")
        assert forbidden.status_code == 403

        # Админ имеет доступ и может переводить статусы
        client.cookies.update(_auth_cookie(admin))
        assert (await client.get(f"/orders/{order_data['id']}")).status_code == 200

        # Недопустимый переход new -> done -> 400
        bad_status = await client.patch(
            f"/orders/{order_data['id']}/status",
            json={"status": "done"},
        )
        assert bad_status.status_code == 400

        # Корректные переходы new -> paid -> done
        paid = await client.patch(
            f"/orders/{order_data['id']}/status",
            json={"status": "paid"},
        )
        assert paid.status_code == 200
        assert paid.json()["status"] == "paid"

        done = await client.patch(
            f"/orders/{order_data['id']}/status",
            json={"status": "done"},
        )
        assert done.status_code == 200
        assert done.json()["status"] == "done"


@pytest.mark.asyncio
async def test_cancel_order_restores_stock() -> None:
    app, _, user1, _, admin, products = _make_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=_auth_cookie(user1),
    ) as client:
        await client.post("/cart/items", json={"product_id": 1, "quantity": 2})
        order = (await client.post("/orders")).json()
        assert products[0].stock == 3

        client.cookies.update(_auth_cookie(admin))
        cancelled = await client.patch(
            f"/orders/{order['id']}/status",
            json={"status": "cancelled"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert products[0].stock == 5


@pytest.mark.asyncio
async def test_cart_checkout_and_orders_html_pages() -> None:
    app, _, user1, _, _, _ = _make_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Гость перенаправляется на /auth/login
        guest_cart = await client.get("/cart", headers={"Accept": "text/html"})
        assert guest_cart.status_code == 302
        assert guest_cart.headers["location"] == "/auth/login"

        # Авторизованный пользователь видит страницы
        client.cookies.update(_auth_cookie(user1))
        cart_html = await client.get("/cart", headers={"Accept": "text/html"})
        assert cart_html.status_code == 200
        assert "Корзина" in cart_html.text

        checkout_html = await client.get("/orders/checkout", headers={"Accept": "text/html"})
        assert checkout_html.status_code == 200
        assert "Оформление заказа" in checkout_html.text

        orders_html = await client.get("/orders", headers={"Accept": "text/html"})
        assert orders_html.status_code == 200
        assert "Мои заказы" in orders_html.text
