import secrets
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user_optional,
    require_admin,
    verify_csrf_if_cookie_present,
)
from app.api.orders import STATUS_LABELS
from app.config import get_settings
from app.database import get_db
from app.models.order import OrderStatus
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminOrderOut,
    CategoryCreate,
    CategoryUpdate,
    ProductCreate,
    ProductUpdate,
    UploadImageOut,
)
from app.schemas.catalog import CategoryOut, ProductOut
from app.services.admin import (
    AdminConflictError,
    AdminNotFoundError,
    create_category,
    create_product,
    delete_category,
    delete_product,
    get_dashboard_stats,
    list_all_categories,
    list_all_orders,
    list_all_products,
    update_category,
    update_product,
)
from app.services.blog import list_posts
from app.services.uploads import (
    ImageTooLargeError,
    InvalidImageTypeError,
    save_uploaded_image,
)

router = APIRouter(prefix="/admin", tags=["admin"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


def _check_admin_page_access(current_user: User | None) -> Response | None:
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администратору",
        )
    return None


def _render_admin_page(
    request: Request,
    template_name: str,
    context: dict[str, object],
) -> Response:
    flash = request.query_params.get("flash")
    flash_type = request.query_params.get("flash_type", "success")
    full_context = {
        **context,
        "flash_message": flash,
        "flash_type": flash_type if flash_type in ("success", "error") else "success",
    }
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context=full_context,
    )
    _ensure_csrf_cookie(request, response)
    return response


# --- HTML-страницы админ-панели ---


@router.get("", include_in_schema=False)
async def admin_dashboard(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response:
    denied = _check_admin_page_access(current_user)
    if denied is not None:
        return denied

    stats = await get_dashboard_stats(session)
    recent_orders = await list_all_orders(session, limit=5)
    return _render_admin_page(
        request,
        "admin/dashboard.html",
        {
            "page_title": "Админ-панель",
            "active_section": "dashboard",
            "current_user": current_user,
            "stats": stats,
            "recent_orders": recent_orders,
            "status_labels": STATUS_LABELS,
        },
    )


@router.get("/products", include_in_schema=False)
async def admin_products_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response:
    denied = _check_admin_page_access(current_user)
    if denied is not None:
        return denied

    products = await list_all_products(session)
    categories = await list_all_categories(session)
    return _render_admin_page(
        request,
        "admin/products.html",
        {
            "page_title": "Товары — Админ-панель",
            "active_section": "products",
            "current_user": current_user,
            "products": products,
            "categories": categories,
        },
    )


@router.get("/categories", include_in_schema=False)
async def admin_categories_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response:
    denied = _check_admin_page_access(current_user)
    if denied is not None:
        return denied

    categories = await list_all_categories(session)
    return _render_admin_page(
        request,
        "admin/categories.html",
        {
            "page_title": "Категории — Админ-панель",
            "active_section": "categories",
            "current_user": current_user,
            "categories": categories,
        },
    )


@router.get("/orders", include_in_schema=False)
async def admin_orders_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> Response:
    denied = _check_admin_page_access(current_user)
    if denied is not None:
        return denied

    orders = await list_all_orders(session, status_filter=order_status)
    return _render_admin_page(
        request,
        "admin/orders.html",
        {
            "page_title": "Заказы — Админ-панель",
            "active_section": "orders",
            "current_user": current_user,
            "orders": orders,
            "active_status": order_status.value if order_status else "",
            "status_labels": STATUS_LABELS,
        },
    )


@router.get("/posts", include_in_schema=False)
async def admin_posts_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response:
    denied = _check_admin_page_access(current_user)
    if denied is not None:
        return denied

    posts, total = await list_posts(session, published_only=False, page=1, per_page=100)
    return _render_admin_page(
        request,
        "admin/posts.html",
        {
            "page_title": "Блог — Админ-панель",
            "active_section": "posts",
            "current_user": current_user,
            "posts": posts,
            "total": total,
        },
    )


# --- JSON API админ-панели ---


@router.post(
    "/api/uploads",
    response_model=UploadImageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузка фото товара (только админ)",
)
async def upload_image(
    file: Annotated[UploadFile, File(...)],
    _admin: Annotated[User, Depends(require_admin)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> UploadImageOut:
    data = await file.read()
    try:
        url, filename, size = save_uploaded_image(data, file.content_type)
    except InvalidImageTypeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ImageTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    return UploadImageOut(url=url, filename=filename, size=size)


@router.get("/api/categories", response_model=list[CategoryOut])
async def api_list_categories(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[CategoryOut]:
    return await list_all_categories(session)


@router.post(
    "/api/categories",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
)
async def api_create_category(
    payload: CategoryCreate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> CategoryOut:
    try:
        return await create_category(session, payload)
    except AdminConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/api/categories/{category_id}", response_model=CategoryOut)
async def api_update_category(
    category_id: int,
    payload: CategoryUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> CategoryOut:
    try:
        return await update_category(session, category_id, payload)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/api/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def api_delete_category(
    category_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> None:
    try:
        await delete_category(session, category_id)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/api/products", response_model=list[ProductOut])
async def api_list_products(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProductOut]:
    return await list_all_products(session)


@router.post(
    "/api/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
)
async def api_create_product(
    payload: ProductCreate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> ProductOut:
    try:
        return await create_product(session, payload)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/api/products/{product_id}", response_model=ProductOut)
async def api_update_product(
    product_id: int,
    payload: ProductUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> ProductOut:
    try:
        return await update_product(session, product_id, payload)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/api/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def api_delete_product(
    product_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> None:
    try:
        await delete_product(session, product_id)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/api/orders", response_model=list[AdminOrderOut])
async def api_list_orders(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> list[AdminOrderOut]:
    return await list_all_orders(session, status_filter=order_status)
