import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user_optional,
    require_admin,
    verify_csrf_if_cookie_present,
)
from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.blog import PostCreate, PostListResponse, PostOut, PostUpdate
from app.services.blog import (
    PostNotFoundError,
    PostSlugExistsError,
    calculate_blog_pages,
    create_post,
    delete_post,
    get_post_by_slug,
    list_posts,
    serialize_post,
    update_post,
)

router = APIRouter(prefix="/blog", tags=["blog"])

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


@router.get("/admin", include_in_schema=False)
async def blog_admin_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response:
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администратору",
        )

    posts, total = await list_posts(session, published_only=False, page=1, per_page=100)
    response = templates.TemplateResponse(
        request=request,
        name="blog/admin.html",
        context={
            "page_title": "Управление блогом",
            "current_user": current_user,
            "posts": posts,
            "total": total,
        },
    )
    _ensure_csrf_cookie(request, response)
    return response


@router.get(
    "",
    response_model=PostListResponse,
    summary="Список постов блога",
)
async def get_blog_posts(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    page: Annotated[int, Query(ge=1, description="Номер страницы")] = 1,
    per_page: Annotated[int, Query(ge=1, le=24, description="Постов на странице")] = 6,
    include_drafts: Annotated[bool, Query(description="Включать черновики (только админ)")] = False,
) -> Response | PostListResponse:
    is_admin = current_user is not None and current_user.role == UserRole.ADMIN.value
    if include_drafts and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Просмотр черновиков доступен только администратору",
        )

    posts, total = await list_posts(
        session,
        published_only=not include_drafts,
        page=page,
        per_page=per_page,
    )
    pages = calculate_blog_pages(total, per_page)

    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="blog/list.html",
            context={
                "page_title": "Блог",
                "current_user": current_user,
                "is_admin": is_admin,
                "posts": posts,
                "page": page,
                "per_page": per_page,
                "pages": pages,
                "total": total,
            },
        )

    return PostListResponse(
        items=posts,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=PostOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создать пост блога (только админ)",
)
async def create_blog_post(
    payload: PostCreate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> PostOut:
    try:
        return await create_post(session, payload)
    except PostSlugExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch(
    "/{post_id:int}",
    response_model=PostOut,
    summary="Редактировать пост блога (только админ)",
)
async def update_blog_post(
    post_id: int,
    payload: PostUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> PostOut:
    try:
        return await update_post(session, post_id, payload)
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PostSlugExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/{post_id:int}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить пост блога (только админ)",
)
async def delete_blog_post(
    post_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> None:
    try:
        await delete_post(session, post_id)
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{slug}",
    response_model=PostOut,
    summary="Страница поста блога",
)
async def get_blog_post_detail(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response | PostOut:
    is_admin = current_user is not None and current_user.role == UserRole.ADMIN.value
    post = await get_post_by_slug(session, slug, published_only=not is_admin)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Статья не найдена")

    post_out = serialize_post(post)

    if _wants_html(request):
        return templates.TemplateResponse(
            request=request,
            name="blog/detail.html",
            context={
                "page_title": post_out.title,
                "current_user": current_user,
                "is_admin": is_admin,
                "post": post_out,
            },
        )

    return post_out
