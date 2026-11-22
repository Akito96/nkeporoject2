import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_current_user_optional,
    verify_csrf_if_cookie_present,
)
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.schemas.auth import UserLogin, UserOut, UserRegister
from app.services.auth import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    authenticate_user,
    create_access_token,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.access_token_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )


def _issue_csrf_token(request: Request, response: Response) -> str:
    settings = get_settings()
    token = request.cookies.get(settings.csrf_cookie_name) or secrets.token_urlsafe(32)
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return token


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> HTMLResponse:
    response = templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "current_user": current_user,
            "page_title": "Вход",
            "debug": get_settings().debug,
        },
    )
    _issue_csrf_token(request, response)
    return response


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> HTMLResponse:
    response = templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={"current_user": current_user, "page_title": "Регистрация"},
    )
    _issue_csrf_token(request, response)
    return response


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация нового пользователя",
)
async def register(
    payload: UserRegister,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> UserOut:
    try:
        user = await register_user(session, payload.email, payload.password)
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    token = create_access_token(user_id=user.id, role=user.role)
    _set_auth_cookie(response, token)
    return UserOut.model_validate(user)


@router.post(
    "/login",
    response_model=UserOut,
    summary="Вход в аккаунт",
)
async def login(
    payload: UserLogin,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> UserOut:
    try:
        user = await authenticate_user(session, payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    token = create_access_token(user_id=user.id, role=user.role)
    _set_auth_cookie(response, token)
    return UserOut.model_validate(user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Выход из аккаунта",
)
async def logout(
    response: Response,
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> None:
    settings = get_settings()
    response.delete_cookie(key=settings.access_token_cookie_name, path="/")


@router.get(
    "/me",
    response_model=UserOut,
    summary="Информация о текущем пользователе",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserOut:
    return UserOut.model_validate(current_user)
