from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import create_app
from app.models.sticker import Sticker
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password


class _ScalarList:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class InMemoryStickerSession:
    def __init__(self, users: list[User], stickers: list[Sticker] | None = None) -> None:
        self.users = list(users)
        self.stickers = list(stickers or [])
        self._next_id = max((s.id for s in self.stickers), default=0) + 1

    async def scalar(self, stmt: Any) -> Any:
        compiled = stmt.compile()
        sql_low = str(compiled).lower()
        params = compiled.params

        if "from users" in sql_low and "id_1" in params:
            return next((u for u in self.users if u.id == params["id_1"]), None)

        if "max(stickers.z)" in sql_low:
            return max((s.z for s in self.stickers), default=0)

        if "from stickers" in sql_low and "id_1" in params:
            return next((s for s in self.stickers if s.id == params["id_1"]), None)

        return None

    async def scalars(self, stmt: Any) -> _ScalarList:
        sql_low = str(stmt.compile()).lower()
        if "from stickers" in sql_low:
            ordered = sorted(self.stickers, key=lambda s: (s.z, s.id))
            return _ScalarList(ordered)
        return _ScalarList([])

    def add(self, obj: Sticker) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)
        self.stickers.append(obj)

    async def delete(self, obj: Sticker) -> None:
        self.stickers = [s for s in self.stickers if s.id != obj.id]

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None


def _make_sticker_fixture() -> tuple[FastAPI, InMemoryStickerSession, User, User]:
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
    session = InMemoryStickerSession([user, admin])
    app = create_app()

    async def override_get_db() -> AsyncGenerator[InMemoryStickerSession, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return app, session, user, admin


def _cookie(user: User) -> dict[str, str]:
    return {"access_token": create_access_token(user.id, user.role)}


@pytest.mark.asyncio
async def test_stickers_access_control() -> None:
    app, _, user, admin = _make_sticker_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        assert (await client.get("/admin/stickers")).status_code == 302
        assert (await client.get("/stickers")).status_code == 401

        client.cookies.update(_cookie(user))
        assert (await client.get("/admin/stickers")).status_code == 403
        assert (await client.get("/stickers")).status_code == 403

        client.cookies.update(_cookie(admin))
        page = await client.get("/admin/stickers")
        assert page.status_code == 200
        assert "Доска стикеров" in page.text
        assert "stickers.js" in page.text


@pytest.mark.asyncio
async def test_stickers_crud_position_z_index_and_validation() -> None:
    app, _, _, admin = _make_sticker_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=_cookie(admin),
    ) as client:
        # Невалидный цвет и отрицательные координаты -> 422
        assert (
            await client.post("/stickers", json={"text": "Тест", "color": "red"})
        ).status_code == 422
        assert (
            await client.post("/stickers", json={"text": "Тест", "x": -10, "y": 5})
        ).status_code == 422

        # Создаём два стикера — z-index автоматически растёт
        s1 = await client.post(
            "/stickers",
            json={"text": "Заказать молоко", "color": "#fff3b0", "x": 20, "y": 30},
        )
        assert s1.status_code == 201
        d1 = s1.json()
        assert d1["color"] == "#FFF3B0"
        assert d1["z"] == 1

        s2 = await client.post(
            "/stickers",
            json={"text": "Проверить кофемолку", "color": "#CAFFBF", "x": 100, "y": 60},
        )
        assert s2.status_code == 201
        assert s2.json()["z"] == 2

        # Сохранение новой позиции и z-index при отпускании (PATCH /stickers/{id})
        moved = await client.patch(
            f"/stickers/{d1['id']}",
            json={"x": 240, "y": 150, "z": 5, "text": "Заказать овсяное молоко"},
        )
        assert moved.status_code == 200
        assert moved.json()["x"] == 240
        assert moved.json()["y"] == 150
        assert moved.json()["z"] == 5
        assert moved.json()["text"] == "Заказать овсяное молоко"

        # Список отсортирован по z-index (s2 с z=2 перед s1 с z=5)
        listing = await client.get("/stickers")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [s2.json()["id"], d1["id"]]

        # Удаление и 404 при повторном удалении
        assert (await client.delete(f"/stickers/{d1['id']}")).status_code == 204
        assert (await client.delete(f"/stickers/{d1['id']}")).status_code == 404
