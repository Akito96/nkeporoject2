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
    require_admin,
    verify_csrf_if_cookie_present,
)
from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.orders import OrderOut, OrderStatusUpdate
from app.services.cart import InsufficientStockError, get_cart_summary
from app.services.orders import (
    EmptyCartError,
    InvalidOrderStatusTransitionError,
    OrderNotFoundError,
    create_order_from_cart,
    get_order_by_id,
    list_user_orders,
    serialize_order,
    update_order_status,
)
from app.services.receipt import generate_order_receipt_pdf

router = APIRouter(prefix="/orders", tags=["orders"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

STATUS_LABELS: dict[str, str] = {
    "new": "Новый",
    "paid": "Оплачен",
    "done": "Выполнен",
    "cancelled": "Отменён",
}


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


@router.get("/checkout", include_in_schema=False)
async def checkout_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response:
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    cart_data = await get_cart_summary(session, current_user.id)
    response = templates.TemplateResponse(
        request=request,
        name="orders/checkout.html",
        context={
            "page_title": "Оформление заказа",
            "current_user": current_user,
            "cart": cart_data,
        },
    )
    _ensure_csrf_cookie(request, response)
    return response


@router.post(
    "",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Оформить заказ из корзины",
)
async def create_order(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> OrderOut:
    try:
        return await create_order_from_cart(session, current_user.id)
    except EmptyCartError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "",
    response_model=list[OrderOut],
    summary="История заказов пользователя",
)
async def get_orders(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response | list[OrderOut]:
    if current_user is None:
        if _wants_html(request):
            return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )

    orders = await list_user_orders(session, current_user.id)

    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="orders/list.html",
            context={
                "page_title": "Мои заказы",
                "current_user": current_user,
                "orders": orders,
                "status_labels": STATUS_LABELS,
            },
        )

    return orders


@router.get(
    "/{order_id}",
    response_model=OrderOut,
    summary="Детали заказа",
)
async def get_order_detail(
    order_id: int,
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response | OrderOut:
    if current_user is None:
        if _wants_html(request):
            return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )

    order = await get_order_by_id(session, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")

    if order.user_id != current_user.id and current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к этому заказу",
        )

    order_out = serialize_order(order)

    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="orders/detail.html",
            context={
                "page_title": f"Заказ №{order_out.id}",
                "current_user": current_user,
                "order": order_out,
                "status_labels": STATUS_LABELS,
            },
        )

    return order_out


@router.get(
    "/{order_id}/receipt",
    summary="Скачать PDF-чек заказа",
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "PDF-чек заказа",
        }
    },
)
async def download_order_receipt(
    order_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    order = await get_order_by_id(session, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")

    if order.user_id != current_user.id and current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к чеку этого заказа",
        )

    order_out = serialize_order(order)
    customer_email = (
        current_user.email if order.user_id == current_user.id else None
    )
    pdf_bytes = generate_order_receipt_pdf(order_out, customer_email=customer_email)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="receipt-order-{order.id}.pdf"',
        },
    )


@router.patch(
    "/{order_id}/status",
    response_model=OrderOut,
    summary="Обновить статус заказа (только админ)",
)
async def patch_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> OrderOut:
    try:
        return await update_order_status(session, order_id, payload.status)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidOrderStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
