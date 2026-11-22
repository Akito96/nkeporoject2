import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.services.auth import (
    InvalidAuthTokenError,
    decode_access_token,
    get_user_by_id,
)


def _extract_token(request: Request) -> str | None:
    settings = get_settings()
    token = request.cookies.get(settings.access_token_cookie_name)
    if token:
        return token

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.removeprefix("Bearer ").strip()
    return None


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )

    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (InvalidAuthTokenError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный токен",
        ) from exc

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )
    return user


async def get_current_user_optional(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    try:
        return await get_current_user(request, session)
    except HTTPException:
        return None


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администратору",
        )
    return current_user


def verify_csrf_if_cookie_present(request: Request) -> None:
    """Проверяет совпадение CSRF-токена в cookie и заголовке X-CSRF-Token для браузерных форм."""
    settings = get_settings()
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    if not csrf_cookie:
        return

    csrf_header = request.headers.get("X-CSRF-Token", "")
    if not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Неверный CSRF-токен",
        )
