import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
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
from app.schemas.cart import CartItemAdd, CartItemUpdate, CartOut
from app.services.cart import (
    CartItemNotFoundError,
    CartProductNotFoundError,
    InsufficientStockError,
    add_to_cart,
    clear_cart,
    get_cart_summary,
    remove_cart_item,
    update_cart_item,
)

router = APIRouter(prefix="/cart", tags=["cart"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "").lower()
    if "text/html" not in accept:
        return False
    if "application/json" in accept:
        return accept.index("text/html") < accept.index("application/json")
    return True


def _ensure_csrf_cookie(request: Request, response: Response) -> None:
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


@router.get(
    "",
    response_model=CartOut,
    summary="Получить корзину пользователя",
)
async def get_cart(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response | CartOut:
    if current_user is None:
        if _wants_html(request):
            return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )

    cart_data = await get_cart_summary(session, current_user.id)

    if _wants_html(request):
        response = templates.TemplateResponse(
            request=request,
            name="cart/index.html",
            context={
                "page_title": "Корзина",
                "current_user": current_user,
                "cart": cart_data,
            },
        )
        _ensure_csrf_cookie(request, response)
        return response

    return cart_data


@router.post(
    "/items",
    response_model=CartOut,
    status_code=status.HTTP_200_OK,
    summary="Добавить товар в корзину",
)
async def add_item(
    payload: CartItemAdd,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> CartOut:
    try:
        return await add_to_cart(session, current_user.id, payload.product_id, payload.quantity)
    except CartProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch(
    "/items/{product_id}",
    response_model=CartOut,
    summary="Изменить количество товара в корзине",
)
async def update_item(
    product_id: int,
    payload: CartItemUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> CartOut:
    try:
        return await update_cart_item(session, current_user.id, product_id, payload.quantity)
    except (CartItemNotFoundError, CartProductNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/items/{product_id}",
    response_model=CartOut,
    summary="Удалить товар из корзины",
)
async def delete_item(
    product_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> CartOut:
    try:
        return await remove_cart_item(session, current_user.id, product_id)
    except CartItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "",
    response_model=CartOut,
    summary="Очистить корзину",
)
async def clear_user_cart(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> CartOut:
    return await clear_cart(session, current_user.id)
