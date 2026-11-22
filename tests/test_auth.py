from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import require_admin
from app.database import get_db
from app.main import create_app
from app.models.user import User, UserRole
from app.services.auth import hash_password


class InMemoryAuthSession:
    """Минимальная async-сессия в памяти для изоляции auth-тестов от внешней БД."""

    def __init__(self, initial_users: list[User] | None = None) -> None:
        self._users: list[User] = list(initial_users or [])
        self._next_id: int = max((u.id for u in self._users), default=0) + 1

    async def scalar(self, stmt: Any) -> User | None:
        params = stmt.compile().params
        if "email_1" in params:
            email = params["email_1"]
            return next((u for u in self._users if u.email == email), None)
        if "id_1" in params:
            user_id = params["id_1"]
            return next((u for u in self._users if u.id == user_id), None)
        return None

    def add(self, obj: User) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)
        self._users.append(obj)

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: User) -> None:
        return None


def _build_test_app(session: InMemoryAuthSession) -> FastAPI:
    app = create_app()

    async def override_get_db() -> AsyncGenerator[InMemoryAuthSession, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db

    @app.get("/_test/admin-only")
    async def admin_only(
        admin: Annotated[User, Depends(require_admin)],
    ) -> dict[str, str]:
        return {"email": admin.email, "role": admin.role}

    return app


@pytest.mark.asyncio
async def test_register_success_and_me() -> None:
    session = InMemoryAuthSession()
    app = _build_test_app(session)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/auth/register",
            json={"email": "Guest@Coffee.Local", "password": "StrongPassword123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "guest@coffee.local"
        assert data["role"] == "user"
        assert "password_hash" not in data

        set_cookie = response.headers.get("set-cookie", "").lower()
        assert "access_token=" in set_cookie
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie

        me_response = await client.get("/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "guest@coffee.local"


@pytest.mark.asyncio
async def test_register_duplicate_email() -> None:
    session = InMemoryAuthSession()
    app = _build_test_app(session)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await client.post(
            "/auth/register",
            json={"email": "dup@coffee.local", "password": "Password123"},
        )
        assert first.status_code == 201

        second = await client.post(
            "/auth/register",
            json={"email": "DUP@coffee.local", "password": "AnotherPassword123"},
        )
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_register_validation_errors() -> None:
    session = InMemoryAuthSession()
    app = _build_test_app(session)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        bad_email = await client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "ValidPassword123"},
        )
        assert bad_email.status_code == 422

        short_password = await client.post(
            "/auth/register",
            json={"email": "ok@coffee.local", "password": "short"},
        )
        assert short_password.status_code == 422


@pytest.mark.asyncio
async def test_login_wrong_password_and_success() -> None:
    user = User(
        id=1,
        email="user@coffee.local",
        password_hash=hash_password("CorrectPassword1"),
        role=UserRole.USER.value,
        created_at=datetime.now(UTC),
    )
    session = InMemoryAuthSession([user])
    app = _build_test_app(session)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        bad_login = await client.post(
            "/auth/login",
            json={"email": "user@coffee.local", "password": "WrongPassword!"},
        )
        assert bad_login.status_code == 401

        good_login = await client.post(
            "/auth/login",
            json={"email": "user@coffee.local", "password": "CorrectPassword1"},
        )
        assert good_login.status_code == 200
        assert good_login.json()["email"] == "user@coffee.local"
        assert "access_token=" in good_login.headers.get("set-cookie", "").lower()


@pytest.mark.asyncio
async def test_me_without_or_invalid_token() -> None:
    session = InMemoryAuthSession()
    app = _build_test_app(session)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        no_auth = await client.get("/auth/me")
        assert no_auth.status_code == 401

        client.cookies.set("access_token", "invalid.jwt.token")
        bad_auth = await client.get("/auth/me")
        assert bad_auth.status_code == 401


@pytest.mark.asyncio
async def test_admin_route_access_control() -> None:
    regular_user = User(
        id=1,
        email="user@coffee.local",
        password_hash=hash_password("UserPass123!"),
        role=UserRole.USER.value,
        created_at=datetime.now(UTC),
    )
    admin_user = User(
        id=2,
        email="admin@coffee.local",
        password_hash=hash_password("AdminPass123!"),
        role=UserRole.ADMIN.value,
        created_at=datetime.now(UTC),
    )
    session = InMemoryAuthSession([regular_user, admin_user])
    app = _build_test_app(session)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Без авторизации -> 401
        anon = await client.get("/_test/admin-only")
        assert anon.status_code == 401

        # Обычный пользователь -> 403
        await client.post(
            "/auth/login",
            json={"email": "user@coffee.local", "password": "UserPass123!"},
        )
        forbidden = await client.get("/_test/admin-only")
        assert forbidden.status_code == 403

        # Администратор -> 200
        await client.post(
            "/auth/login",
            json={"email": "admin@coffee.local", "password": "AdminPass123!"},
        )
        allowed = await client.get("/_test/admin-only")
        assert allowed.status_code == 200
        assert allowed.json() == {"email": "admin@coffee.local", "role": "admin"}


@pytest.mark.asyncio
async def test_html_pages_and_csrf_protection() -> None:
    session = InMemoryAuthSession()
    app = _build_test_app(session)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        login_page = await client.get("/auth/login")
        assert login_page.status_code == 200
        assert "Вход в аккаунт" in login_page.text

        register_page = await client.get("/auth/register")
        assert register_page.status_code == 200
        assert "Регистрация" in register_page.text

        csrf_token = client.cookies.get("csrf_token")
        assert csrf_token

        # С cookie csrf_token, но без заголовка X-CSRF-Token -> 403
        blocked = await client.post(
            "/auth/register",
            json={"email": "csrf@coffee.local", "password": "Password123!"},
        )
        assert blocked.status_code == 403

        # С корректным заголовком X-CSRF-Token -> 201
        ok = await client.post(
            "/auth/register",
            headers={"X-CSRF-Token": csrf_token},
            json={"email": "csrf@coffee.local", "password": "Password123!"},
        )
        assert ok.status_code == 201
