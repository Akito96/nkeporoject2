from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import admin as admin_api
from app.database import get_db
from app.main import create_app
from app.models.blog import Post
from app.models.catalog import Category, Product
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password
from app.services.uploads import (
    MAX_IMAGE_SIZE_BYTES,
    ImageTooLargeError,
    InvalidImageTypeError,
    save_uploaded_image,
)

# Минимальный валидный PNG-заголовок для тестов загрузки
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class _ScalarList:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class InMemoryAdminSession:
    def __init__(
        self,
        users: list[User],
        categories: list[Category],
        products: list[Product],
        orders: list[Order],
        posts: list[Post],
    ) -> None:
        self.users = list(users)
        self.categories = list(categories)
        self.products = list(products)
        self.orders = list(orders)
        self.posts = list(posts)
        self._next_cat_id = max((c.id for c in self.categories), default=0) + 1
        self._next_prod_id = max((p.id for p in self.products), default=0) + 1

    async def scalar(self, stmt: Any) -> Any:
        compiled = stmt.compile()
        sql = str(compiled)
        sql_low = sql.lower()
        params = compiled.params

        if "from users" in sql_low:
            if "id_1" in params:
                return next((u for u in self.users if u.id == params["id_1"]), None)
            if "email_1" in params:
                return next((u for u in self.users if u.email == params["email_1"]), None)

        if "count(products.id)" in sql_low:
            if "category_id_1" in params:
                return sum(1 for p in self.products if p.category_id == params["category_id_1"])
            return len(self.products)
        if "count(categories.id)" in sql_low:
            return len(self.categories)
        if "count(orders.id)" in sql_low:
            return len(self.orders)
        if "count(posts.id)" in sql_low:
            return len(self.posts)
        if "count(order_items.id)" in sql_low:
            pid = params.get("product_id_1")
            return sum(
                1 for o in self.orders for item in o.items if item.product_id == pid
            )

        if "from categories" in sql_low:
            if "id_1" in params:
                return next((c for c in self.categories if c.id == params["id_1"]), None)
            if "slug_1" in params:
                return next((c for c in self.categories if c.slug == params["slug_1"]), None)
            if "name_1" in params:
                return next((c for c in self.categories if c.name == params["name_1"]), None)

        if "from products" in sql_low and "id_1" in params:
            return next((p for p in self.products if p.id == params["id_1"]), None)

        return None

    async def scalars(self, stmt: Any) -> _ScalarList:
        compiled = stmt.compile()
        sql_low = str(compiled).lower()
        params = compiled.params

        if "from categories" in sql_low:
            return _ScalarList(sorted(self.categories, key=lambda c: c.name))
        if "from products" in sql_low:
            return _ScalarList(sorted(self.products, key=lambda p: p.id, reverse=True))
        if "from orders" in sql_low:
            items = list(self.orders)
            if "status_1" in params:
                items = [o for o in items if o.status == params["status_1"]]
            return _ScalarList(items)
        if "from posts" in sql_low:
            return _ScalarList(list(self.posts))
        return _ScalarList([])

    def add(self, obj: Any) -> None:
        if isinstance(obj, Category):
            if getattr(obj, "id", None) is None:
                obj.id = self._next_cat_id
                self._next_cat_id += 1
            self.categories.append(obj)
        elif isinstance(obj, Product):
            if getattr(obj, "id", None) is None:
                obj.id = self._next_prod_id
                self._next_prod_id += 1
            self.products.append(obj)

    async def delete(self, obj: Any) -> None:
        if isinstance(obj, Category):
            self.categories = [c for c in self.categories if c.id != obj.id]
        elif isinstance(obj, Product):
            self.products = [p for p in self.products if p.id != obj.id]

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None


def _make_admin_fixture() -> tuple[FastAPI, InMemoryAdminSession, User, User]:
    user = User(
        id=1,
        email="user@coffee.local",
        password_hash=hash_password("UserPass123"),
        role=UserRole.USER.value,
        created_at=datetime.now(UTC),
    )
    admin = User(
        id=2,
        email="admin@coffee.local",
        password_hash=hash_password("AdminPass123"),
        role=UserRole.ADMIN.value,
        created_at=datetime.now(UTC),
    )
    cat_coffee = Category(id=1, name="Кофе", slug="coffee")
    cat_empty = Category(id=2, name="Мерч", slug="merch")
    prod = Product(
        id=1,
        category_id=1,
        name="Эспрессо",
        description="Шот арабики",
        price=Decimal("180.00"),
        image=None,
        stock=20,
        is_active=True,
        category=cat_coffee,
    )
    order = Order(
        id=10,
        user_id=1,
        status=OrderStatus.NEW.value,
        total=Decimal("180.00"),
        created_at=datetime.now(UTC),
        user=user,
        items=[
            OrderItem(
                id=1,
                order_id=10,
                product_id=1,
                quantity=1,
                price=Decimal("180.00"),
                product=prod,
            )
        ],
    )
    post = Post(
        id=1,
        title="Тестовая статья",
        slug="test-article",
        cover=None,
        body_md="Текст",
        is_published=True,
        published_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    session = InMemoryAdminSession([user, admin], [cat_coffee, cat_empty], [prod], [order], [post])
    app = create_app()

    async def override_get_db() -> AsyncGenerator[InMemoryAdminSession, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return app, session, user, admin


def _cookie(user: User) -> dict[str, str]:
    return {"access_token": create_access_token(user.id, user.role)}


def test_upload_image_service_validation(tmp_path: Path) -> None:
    url, filename, size = save_uploaded_image(
        VALID_PNG_BYTES,
        "image/png",
        upload_dir=tmp_path,
    )
    assert url == f"/static/uploads/{filename}"
    assert filename.endswith(".png")
    assert size == len(VALID_PNG_BYTES)
    assert (tmp_path / filename).exists()

    # Недопустимый MIME-тип
    with pytest.raises(InvalidImageTypeError):
        save_uploaded_image(b"plain text", "text/plain", upload_dir=tmp_path)

    # Подмена Content-Type (байты не соответствуют PNG)
    with pytest.raises(InvalidImageTypeError):
        save_uploaded_image(b"not-a-real-png-file", "image/png", upload_dir=tmp_path)

    # Превышение размера > 5 МБ
    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * MAX_IMAGE_SIZE_BYTES
    with pytest.raises(ImageTooLargeError):
        save_uploaded_image(oversized, "image/png", upload_dir=tmp_path)


@pytest.mark.asyncio
async def test_admin_pages_and_api_access_control() -> None:
    app, _, user, admin = _make_admin_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Гость -> редирект на HTML и 401 на API
        assert (await client.get("/admin")).status_code == 302
        assert (await client.get("/admin/api/products")).status_code == 401

        # Обычный пользователь -> 403 везде
        client.cookies.update(_cookie(user))
        assert (await client.get("/admin")).status_code == 403
        assert (await client.get("/admin/products")).status_code == 403
        assert (await client.get("/admin/api/products")).status_code == 403

        # Админ -> 200 на все разделы с единым боковым меню
        client.cookies.update(_cookie(admin))
        for path in (
            "/admin",
            "/admin/products",
            "/admin/categories",
            "/admin/orders",
            "/admin/posts",
        ):
            resp = await client.get(path)
            assert resp.status_code == 200
            assert "Кофейня · Admin" in resp.text


@pytest.mark.asyncio
async def test_admin_categories_and_products_crud() -> None:
    app, _, _, admin = _make_admin_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=_cookie(admin),
    ) as client:
        # Создание категории с автогенерацией slug
        c_create = await client.post("/admin/api/categories", json={"name": "Выпечка"})
        assert c_create.status_code == 201
        cat_id = c_create.json()["id"]
        assert c_create.json()["slug"] == "vypechka"

        # Дубликат slug -> 409
        c_dup = await client.post(
            "/admin/api/categories",
            json={"name": "Другая", "slug": "vypechka"},
        )
        assert c_dup.status_code == 409

        # Редактирование категории
        c_upd = await client.patch(
            f"/admin/api/categories/{cat_id}",
            json={"name": "Свежая выпечка"},
        )
        assert c_upd.status_code == 200
        assert c_upd.json()["name"] == "Свежая выпечка"

        # Нельзя удалить категорию #1, в которой есть товар -> 409
        assert (await client.delete("/admin/api/categories/1")).status_code == 409

        # Пустую категорию можно удалить -> 204
        assert (await client.delete(f"/admin/api/categories/{cat_id}")).status_code == 204

        # Создание товара и валидация отрицательной цены
        bad_prod = await client.post(
            "/admin/api/products",
            json={"category_id": 1, "name": "Латте", "price": "-10.00", "stock": 5},
        )
        assert bad_prod.status_code == 422

        p_create = await client.post(
            "/admin/api/products",
            json={"category_id": 1, "name": "Латте", "price": "280.00", "stock": 15},
        )
        assert p_create.status_code == 201
        prod_id = p_create.json()["id"]

        # Редактирование и удаление товара
        p_upd = await client.patch(
            f"/admin/api/products/{prod_id}",
            json={"price": "295.00", "is_active": False},
        )
        assert p_upd.status_code == 200
        assert Decimal(p_upd.json()["price"]) == Decimal("295.00")
        assert p_upd.json()["is_active"] is False

        assert (await client.delete(f"/admin/api/products/{prod_id}")).status_code == 204

        # Товар #1 участвует в заказе -> 409 при попытке удаления
        assert (await client.delete("/admin/api/products/1")).status_code == 409


@pytest.mark.asyncio
async def test_admin_upload_endpoint_and_orders_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, _, admin = _make_admin_fixture()
    monkeypatch.setattr(
        admin_api,
        "save_uploaded_image",
        lambda data, content_type: save_uploaded_image(data, content_type, upload_dir=tmp_path),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=_cookie(admin),
    ) as client:
        ok_upload = await client.post(
            "/admin/api/uploads",
            files={"file": ("latte.png", VALID_PNG_BYTES, "image/png")},
        )
        assert ok_upload.status_code == 201
        assert ok_upload.json()["url"].startswith("/static/uploads/")

        bad_upload = await client.post(
            "/admin/api/uploads",
            files={"file": ("evil.txt", b"hello", "text/plain")},
        )
        assert bad_upload.status_code == 400

        orders_resp = await client.get("/admin/api/orders", params={"status": "new"})
        assert orders_resp.status_code == 200
        orders = orders_resp.json()
        assert len(orders) == 1
        assert orders[0]["user_email"] == "user@coffee.local"
        assert "paid" in orders[0]["allowed_next_statuses"]
