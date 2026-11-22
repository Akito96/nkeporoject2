from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.main import create_app


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


@pytest.mark.asyncio
async def test_health_ok() -> None:
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncMock, None]:
        session = AsyncMock()
        session.execute.return_value = _FakeResult(1)
        yield session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.asyncio
async def test_health_db_unavailable() -> None:
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncMock, None]:
        session = AsyncMock()
        session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("db down"))
        yield session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
