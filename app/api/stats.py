from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_optional, require_admin
from app.api.orders import STATUS_LABELS
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.stats import (
    OrdersByStatusItem,
    RevenueByCategoryItem,
    RevenueByDayItem,
    StatsOverview,
    TopProductItem,
)
from app.services.stats import (
    InvalidDateRangeError,
    build_stats_csv,
    get_orders_by_status,
    get_revenue_by_category,
    get_revenue_by_day,
    get_stats_overview,
    get_top_products,
    resolve_date_range,
)

router = APIRouter(tags=["stats"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/admin/stats", include_in_schema=False)
async def admin_stats_page(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response:
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администратору",
        )

    return templates.TemplateResponse(
        request=request,
        name="admin/stats.html",
        context={
            "page_title": "Аналитика — Админ-панель",
            "active_section": "stats",
            "current_user": current_user,
            "status_labels": STATUS_LABELS,
            "flash_message": None,
            "flash_type": "success",
        },
    )


@router.get(
    "/admin/api/stats/summary",
    response_model=StatsOverview,
    summary="Сводная статистика продаж за период",
)
async def api_stats_summary(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> StatsOverview:
    try:
        return await get_stats_overview(
            session,
            days=days,
            date_from=date_from,
            date_to=date_to,
        )
    except InvalidDateRangeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/admin/api/stats/revenue-by-day",
    response_model=list[RevenueByDayItem],
    summary="Выручка по дням за период",
)
async def api_revenue_by_day(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> list[RevenueByDayItem]:
    try:
        _, _, start_dt, end_dt = resolve_date_range(
            days=days, date_from=date_from, date_to=date_to
        )
    except InvalidDateRangeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await get_revenue_by_day(session, start_dt, end_dt)


@router.get(
    "/admin/api/stats/top-products",
    response_model=list[TopProductItem],
    summary="Топ-10 товаров по выручке за период",
)
async def api_top_products(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> list[TopProductItem]:
    try:
        _, _, start_dt, end_dt = resolve_date_range(
            days=days, date_from=date_from, date_to=date_to
        )
    except InvalidDateRangeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await get_top_products(session, start_dt, end_dt, limit=10)


@router.get(
    "/admin/api/stats/orders-by-status",
    response_model=list[OrdersByStatusItem],
    summary="Количество заказов по статусам за период",
)
async def api_orders_by_status(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> list[OrdersByStatusItem]:
    try:
        _, _, start_dt, end_dt = resolve_date_range(
            days=days, date_from=date_from, date_to=date_to
        )
    except InvalidDateRangeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await get_orders_by_status(session, start_dt, end_dt)


@router.get(
    "/admin/api/stats/revenue-by-category",
    response_model=list[RevenueByCategoryItem],
    summary="Выручка по категориям за период",
)
async def api_revenue_by_category(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> list[RevenueByCategoryItem]:
    try:
        _, _, start_dt, end_dt = resolve_date_range(
            days=days, date_from=date_from, date_to=date_to
        )
    except InvalidDateRangeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await get_revenue_by_category(session, start_dt, end_dt)


@router.get(
    "/admin/api/stats/export.csv",
    summary="Экспорт аналитики в CSV",
)
async def api_export_stats_csv(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> Response:
    try:
        overview = await get_stats_overview(
            session,
            days=days,
            date_from=date_from,
            date_to=date_to,
        )
    except InvalidDateRangeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    csv_content = build_stats_csv(overview)
    filename = f"coffee-stats-{overview.date_from}-{overview.date_to}.csv"
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
