from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import products as products_api
from app.database import get_db
from app.main import create_app
from app.models.catalog import Category, Product
from app.schemas.catalog import ProductSort


def _sample_catalog() -> tuple[list[Category], list[Product]]:
    cat_coffee = Category(id=1, name="Классический кофе", slug="classic-coffee")
    cat_desserts = Category(id=2, name="Десерты", slug="desserts")

    items = [
        Product(
            id=1,
            category_id=1,
            name="Эспрессо",
            description="Плотный шот арабики",
            price=Decimal("180.00"),
            image="/static/img/espresso.jpg",
            stock=10,
            is_active=True,
            category=cat_coffee,
        ),
        Product(
            id=2,
            category_id=1,
            name="Капучино",
            description="С бархатной пеной",
            price=Decimal("260.00"),
            image="/static/img/cappuccino.jpg",
            stock=8,
            is_active=True,
            category=cat_coffee,
        ),
        Product(
            id=3,
            category_id=2,
            name="Баскский чизкейк",
            description="Нежный сливочный десерт",
            price=Decimal("380.00"),
            image="/static/img/cheesecake.jpg",
            stock=0,
            is_active=True,
            category=cat_desserts,
        ),
        Product(
            id=4,
            category_id=2,
            name="Архивный десерт",
            description="Скрытый товар",
            price=Decimal("150.00"),
            image=None,
            stock=5,
            is_active=False,
            category=cat_desserts,
        ),
    ]
    return [cat_coffee, cat_desserts], items


def _build_catalog_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    categories, all_products = _sample_catalog()
    app = create_app()

    async def override_get_db() -> AsyncGenerator[None, None]:
        yield None

    app.dependency_overrides[get_db] = override_get_db

    async def fake_list_categories(_session: Any) -> list[Category]:
        return categories

    async def fake_list_products(
        _session: Any,
        *,
        category_slug: str | None = None,
        search: str | None = None,
        sort: ProductSort = ProductSort.DEFAULT,
        page: int = 1,
        per_page: int = 12,
        active_only: bool = True,
    ) -> tuple[list[Product], int]:
        filtered = list(all_products)
        if active_only:
            filtered = [p for p in filtered if p.is_active]
        if category_slug:
            slug = category_slug.strip().lower()
            filtered = [p for p in filtered if p.category and p.category.slug == slug]
        if search and search.strip():
            term = search.strip().lower()
            filtered = [p for p in filtered if term in p.name.lower()]

        if sort == ProductSort.PRICE_ASC:
            filtered.sort(key=lambda p: (p.price, p.id))
        elif sort == ProductSort.PRICE_DESC:
            filtered.sort(key=lambda p: (-p.price, p.id))
        elif sort == ProductSort.NAME_ASC:
            filtered.sort(key=lambda p: (p.name.lower(), p.id))
        else:
            filtered.sort(key=lambda p: p.id)

        total = len(filtered)
        start = (page - 1) * per_page
        return filtered[start : start + per_page], total

    async def fake_get_product_by_id(
        _session: Any,
        product_id: int,
        *,
        active_only: bool = True,
    ) -> Product | None:
        for prod in all_products:
            if prod.id == product_id and (not active_only or prod.is_active):
                return prod
        return None

    monkeypatch.setattr(products_api, "list_categories", fake_list_categories)
    monkeypatch.setattr(products_api, "list_products", fake_list_products)
    monkeypatch.setattr(products_api, "get_product_by_id", fake_get_product_by_id)
    return app


@pytest.mark.asyncio
async def test_list_products_filter_search_sort_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_catalog_app(monkeypatch)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Все активные товары (скрытый не попадает)
        resp = await client.get("/products")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3

        # Фильтр по категории
        cat_resp = await client.get("/products", params={"category": "classic-coffee"})
        assert cat_resp.status_code == 200
        assert [item["name"] for item in cat_resp.json()["items"]] == ["Эспрессо", "Капучино"]

        # Поиск по названию без учёта регистра
        search_resp = await client.get("/products", params={"q": "ЧИЗ"})
        assert search_resp.status_code == 200
        assert [item["name"] for item in search_resp.json()["items"]] == ["Баскский чизкейк"]

        # Сортировка по цене по убыванию
        sort_resp = await client.get("/products", params={"sort": "price_desc"})
        assert sort_resp.status_code == 200
        prices = [Decimal(item["price"]) for item in sort_resp.json()["items"]]
        assert prices == [Decimal("380.00"), Decimal("260.00"), Decimal("180.00")]

        # Пагинация
        page_resp = await client.get("/products", params={"page": 2, "per_page": 2})
        assert page_resp.status_code == 200
        page_body = page_resp.json()
        assert page_body["total"] == 3
        assert page_body["pages"] == 2
        assert page_body["page"] == 2
        assert len(page_body["items"]) == 1


@pytest.mark.asyncio
async def test_product_detail_found_and_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_catalog_app(monkeypatch)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        ok = await client.get("/products/1")
        assert ok.status_code == 200
        assert ok.json()["name"] == "Эспрессо"
        assert ok.json()["category"]["slug"] == "classic-coffee"

        # Неактивный товар скрыт -> 404
        inactive = await client.get("/products/4")
        assert inactive.status_code == 404

        # Несуществующий товар -> 404
        missing = await client.get("/products/999")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_catalog_and_detail_html_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_catalog_app(monkeypatch)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        catalog_html = await client.get("/products", headers={"Accept": "text/html"})
        assert catalog_html.status_code == 200
        assert "Меню кофейни" in catalog_html.text
        assert "Эспрессо" in catalog_html.text
        assert "Классический кофе" in catalog_html.text

        empty_html = await client.get(
            "/products",
            params={"q": "несуществующий"},
            headers={"Accept": "text/html"},
        )
        assert empty_html.status_code == 200
        assert "Ничего не найдено" in empty_html.text

        detail_html = await client.get("/products/1", headers={"Accept": "text/html"})
        assert detail_html.status_code == 200
        assert "Эспрессо" in detail_html.text
        assert "Назад в каталог" in detail_html.text
