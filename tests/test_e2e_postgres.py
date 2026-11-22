import os
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import create_app
from app.seed import seed_database

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL не задана (интеграционный тест запускается в CI/Docker с PostgreSQL)",
)
async def test_full_coffee_shop_flow_on_postgres() -> None:
    """Сквозной E2E-сценарий на реальной PostgreSQL БД с миграциями."""
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Очищаем таблицы и загружаем seed-данные
    async with session_factory() as setup_session:
        await setup_session.execute(
            text(
                "TRUNCATE TABLE order_items, orders, cart_items, carts, "
                "stickers, posts, products, categories, users RESTART IDENTITY CASCADE"
            )
        )
        await setup_session.commit()
        await seed_database(setup_session)

    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # 1. Healthcheck с реальным PostgreSQL
            health = await client.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok", "database": "ok"}

            # 2. Каталог из seed-данных
            catalog = await client.get("/products", params={"category": "classic-coffee"})
            assert catalog.status_code == 200
            assert catalog.json()["total"] == 4
            product_id = catalog.json()["items"][0]["id"]
            product_price = Decimal(catalog.json()["items"][0]["price"])

            # 3. Регистрация нового гостя -> добавление в корзину -> оформление заказа
            reg = await client.post(
                "/auth/register",
                json={"email": "e2e@coffee.local", "password": "E2ePassword123!"},
            )
            assert reg.status_code == 201

            cart_add = await client.post(
                "/cart/items",
                json={"product_id": product_id, "quantity": 2},
            )
            assert cart_add.status_code == 200
            assert Decimal(cart_add.json()["total"]) == product_price * 2

            order_resp = await client.post("/orders")
            assert order_resp.status_code == 201
            order_id = order_resp.json()["id"]
            assert Decimal(order_resp.json()["total"]) == product_price * 2

            # 4. Скачивание PDF-чека владельцем
            receipt = await client.get(f"/orders/{order_id}/receipt")
            assert receipt.status_code == 200
            assert receipt.content.startswith(b"%PDF-")

            # 5. Вход админом -> SQL-аналитика, стикеры и блог
            admin_login = await client.post(
                "/auth/login",
                json={"email": "admin@coffee.local", "password": "AdminPassword123!"},
            )
            assert admin_login.status_code == 200

            stats = await client.get("/admin/api/stats/summary", params={"days": 30})
            assert stats.status_code == 200
            assert Decimal(stats.json()["total_revenue"]) == product_price * 2

            sticker = await client.post(
                "/stickers",
                json={"text": "E2E стикер", "color": "#FFF3B0", "x": 40, "y": 50},
            )
            assert sticker.status_code == 201
            sticker_id = sticker.json()["id"]
            moved = await client.patch(
                f"/stickers/{sticker_id}",
                json={"x": 120, "y": 90, "z": 3},
            )
            assert moved.status_code == 200
            assert moved.json()["x"] == 120
    finally:
        await engine.dispose()
