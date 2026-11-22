from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import stats as stats_api
from app.database import get_db
from app.main import create_app
from app.models import Base
from app.models.user import User, UserRole
from app.schemas.stats import (
    OrdersByStatusItem,
    RevenueByCategoryItem,
    RevenueByDayItem,
    StatsOverview,
    TopProductItem,
)
from app.services.auth import create_access_token, hash_password
from app.services.stats import (
    InvalidDateRangeError,
    build_stats_csv,
    resolve_date_range,
)


class _FakeAuthSession:
    def __init__(self, users: list[User]) -> None:
        self.users = users

    async def scalar(self, stmt: Any) -> Any:
        params = stmt.compile().params
        if "id_1" in params:
            return next((u for u in self.users if u.id == params["id_1"]), None)
        return None


def _sample_overview() -> StatsOverview:
    return StatsOverview(
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 22),
        total_revenue=Decimal("1520.00"),
        total_orders=4,
        paid_or_active_orders=3,
        average_check=Decimal("506.67"),
        revenue_by_day=[
            RevenueByDayItem(day=date(2026, 11, 20), revenue=Decimal("520.00"), orders_count=1),
            RevenueByDayItem(day=date(2026, 11, 21), revenue=Decimal("1000.00"), orders_count=2),
        ],
        top_products=[
            TopProductItem(
                product_id=1,
                product_name="Капучино",
                quantity_sold=4,
                revenue=Decimal("1040.00"),
            ),
            TopProductItem(
                product_id=2,
                product_name="Круассан",
                quantity_sold=2,
                revenue=Decimal("480.00"),
            ),
        ],
        orders_by_status=[
            OrdersByStatusItem(status="done", orders_count=2, revenue=Decimal("1000.00")),
            OrdersByStatusItem(status="paid", orders_count=1, revenue=Decimal("520.00")),
            OrdersByStatusItem(status="cancelled", orders_count=1, revenue=Decimal("260.00")),
        ],
        revenue_by_category=[
            RevenueByCategoryItem(
                category_id=1,
                category_name="Классический кофе",
                quantity_sold=4,
                revenue=Decimal("1040.00"),
            ),
            RevenueByCategoryItem(
                category_id=2,
                category_name="Десерты",
                quantity_sold=2,
                revenue=Decimal("480.00"),
            ),
        ],
    )


def _build_stats_app(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, User, User]:
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
    session = _FakeAuthSession([user, admin])
    overview = _sample_overview()

    app = create_app()

    async def override_get_db() -> AsyncGenerator[_FakeAuthSession, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db

    async def fake_overview(*_args: Any, **kwargs: Any) -> StatsOverview:
        resolve_date_range(
            days=kwargs.get("days", 30),
            date_from=kwargs.get("date_from"),
            date_to=kwargs.get("date_to"),
        )
        return overview

    async def fake_by_day(*_args: Any, **_kwargs: Any) -> list[RevenueByDayItem]:
        return overview.revenue_by_day

    async def fake_top(*_args: Any, **_kwargs: Any) -> list[TopProductItem]:
        return overview.top_products

    async def fake_by_status(*_args: Any, **_kwargs: Any) -> list[OrdersByStatusItem]:
        return overview.orders_by_status

    async def fake_by_category(*_args: Any, **_kwargs: Any) -> list[RevenueByCategoryItem]:
        return overview.revenue_by_category

    monkeypatch.setattr(stats_api, "get_stats_overview", fake_overview)
    monkeypatch.setattr(stats_api, "get_revenue_by_day", fake_by_day)
    monkeypatch.setattr(stats_api, "get_top_products", fake_top)
    monkeypatch.setattr(stats_api, "get_orders_by_status", fake_by_status)
    monkeypatch.setattr(stats_api, "get_revenue_by_category", fake_by_category)
    return app, user, admin


def _cookie(user: User) -> dict[str, str]:
    return {"access_token": create_access_token(user.id, user.role)}


def test_composite_analytics_indexes_declared_in_metadata() -> None:
    orders_idx = {idx.name for idx in Base.metadata.tables["orders"].indexes}
    order_items_idx = {idx.name for idx in Base.metadata.tables["order_items"].indexes}
    assert "ix_orders_status_created_at" in orders_idx
    assert "ix_order_items_order_product" in order_items_idx


def test_date_range_validation_and_csv_generation() -> None:
    with pytest.raises(InvalidDateRangeError):
        resolve_date_range(date_from=date(2026, 11, 20), date_to=date(2026, 11, 10))

    csv_text = build_stats_csv(_sample_overview())
    assert csv_text.startswith("\ufeff")
    assert "Капучино;4;1040.00" in csv_text
    assert "Классический кофе;4;1040.00" in csv_text
    assert "Средний чек (₽);506.67" in csv_text


@pytest.mark.asyncio
async def test_stats_endpoints_permissions_and_data(monkeypatch: pytest.MonkeyPatch) -> None:
    app, user, admin = _build_stats_app(monkeypatch)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Гость -> 302 на HTML и 401 на API
        assert (await client.get("/admin/stats")).status_code == 302
        assert (await client.get("/admin/api/stats/summary")).status_code == 401

        # Обычный пользователь -> 403
        client.cookies.update(_cookie(user))
        assert (await client.get("/admin/stats")).status_code == 403
        assert (await client.get("/admin/api/stats/summary")).status_code == 403

        # Админ получает страницу и все аналитические эндпоинты
        client.cookies.update(_cookie(admin))
        page = await client.get("/admin/stats")
        assert page.status_code == 200
        assert "Статистика и аналитика" in page.text
        assert "chart.umd.min.js" in page.text

        summary = await client.get("/admin/api/stats/summary", params={"days": 7})
        assert summary.status_code == 200
        assert Decimal(summary.json()["average_check"]) == Decimal("506.67")

        assert len((await client.get("/admin/api/stats/revenue-by-day")).json()) == 2
        assert len((await client.get("/admin/api/stats/top-products")).json()) == 2
        assert len((await client.get("/admin/api/stats/orders-by-status")).json()) == 3
        assert len((await client.get("/admin/api/stats/revenue-by-category")).json()) == 2

        # Невалидный диапазон дат -> 400
        bad_range = await client.get(
            "/admin/api/stats/summary",
            params={"date_from": "2026-11-22", "date_to": "2026-11-01"},
        )
        assert bad_range.status_code == 400

        # Экспорт в CSV
        csv_resp = await client.get("/admin/api/stats/export.csv", params={"days": 30})
        assert csv_resp.status_code == 200
        assert "text/csv" in csv_resp.headers["content-type"]
        assert "coffee-stats-" in csv_resp.headers["content-disposition"]
        assert "Капучино" in csv_resp.text


@pytest.mark.asyncio
async def test_average_check_zero_orders_edge_case() -> None:
    from app.services.stats import get_average_check_and_totals

    class _ZeroSession:
        async def execute(self, _stmt: Any) -> Any:
            return SimpleNamespace(
                one=lambda: SimpleNamespace(total_revenue=0, orders_count=0, avg_check=0)
            )

    total, count, avg = await get_average_check_and_totals(
        _ZeroSession(),  # type: ignore[arg-type]
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert total == Decimal("0.00")
    assert count == 0
    assert avg == Decimal("0.00")
