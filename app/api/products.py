from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_optional
from app.database import get_db
from app.models.user import User
from app.schemas.catalog import ProductListResponse, ProductOut, ProductSort
from app.services.catalog import (
    calculate_total_pages,
    get_product_by_id,
    list_categories,
    list_products,
)

router = APIRouter(prefix="/products", tags=["products"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "").lower()
    if "text/html" not in accept:
        return False
    if "application/json" in accept:
        return accept.index("text/html") < accept.index("application/json")
    return True


@router.get(
    "",
    response_model=ProductListResponse,
    summary="Список товаров каталога",
)
async def get_products(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    category: Annotated[str | None, Query(description="Slug категории")] = None,
    q: Annotated[str | None, Query(max_length=120, description="Поиск по названию")] = None,
    sort: Annotated[ProductSort, Query(description="Сортировка")] = ProductSort.DEFAULT,
    page: Annotated[int, Query(ge=1, description="Номер страницы")] = 1,
    per_page: Annotated[int, Query(ge=1, le=48, description="Товаров на странице")] = 12,
) -> Response | ProductListResponse:
    products, total = await list_products(
        session,
        category_slug=category,
        search=q,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    pages = calculate_total_pages(total, per_page)

    if _wants_html(request):
        categories = await list_categories(session)
        return templates.TemplateResponse(
            request=request,
            name="products/list.html",
            context={
                "page_title": "Каталог",
                "current_user": current_user,
                "products": products,
                "categories": categories,
                "active_category": (category or "").strip().lower(),
                "search_query": (q or "").strip(),
                "sort": sort.value,
                "page": page,
                "per_page": per_page,
                "pages": pages,
                "total": total,
            },
        )

    return ProductListResponse(
        items=[ProductOut.model_validate(item) for item in products],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get(
    "/{product_id}",
    response_model=ProductOut,
    summary="Карточка товара",
)
async def get_product_detail(
    product_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response | ProductOut:
    product = await get_product_by_id(session, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Товар не найден",
        )

    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="products/detail.html",
            context={
                "page_title": product.name,
                "current_user": current_user,
                "product": product,
            },
        )

    return ProductOut.model_validate(product)
