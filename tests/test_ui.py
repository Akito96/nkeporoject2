import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_404_html_and_json_responses() -> None:
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        html_resp = await client.get(
            "/non-existent-coffee-page",
            headers={"Accept": "text/html"},
        )
        assert html_resp.status_code == 404
        assert "Страница не найдена" in html_resp.text
        assert "/products" in html_resp.text

        json_resp = await client.get(
            "/non-existent-coffee-page",
            headers={"Accept": "application/json"},
        )
        assert json_resp.status_code == 404
        assert "detail" in json_resp.json()


@pytest.mark.asyncio
async def test_500_html_and_json_responses() -> None:
    app = create_app()

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("Unexpected failure")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        html_resp = await client.get(
            "/_test/boom",
            headers={"Accept": "text/html"},
        )
        assert html_resp.status_code == 500
        assert "Внутренняя ошибка сервера" in html_resp.text

        json_resp = await client.get(
            "/_test/boom",
            headers={"Accept": "application/json"},
        )
        assert json_resp.status_code == 500
        assert json_resp.json() == {"detail": "Внутренняя ошибка сервера"}


@pytest.mark.asyncio
async def test_accessibility_landmarks_present_on_auth_pages() -> None:
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/auth/login", headers={"Accept": "text/html"})
        assert resp.status_code == 200
        assert 'class="skip-link"' in resp.text
        assert 'id="main-content"' in resp.text
        assert 'aria-label="Основная навигация"' in resp.text
