import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from app.schemas.stickers import STICKER_PALETTE, StickerCreate, StickerOut, StickerUpdate
from app.services.stickers import (
    StickerNotFoundError,
    create_sticker,
    delete_sticker,
    list_stickers,
    update_sticker,
)

router = APIRouter(tags=["stickers"])

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


@router.get("/admin/stickers", include_in_schema=False)
async def admin_stickers_page(
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

    stickers = await list_stickers(session)
    response = templates.TemplateResponse(
        request=request,
        name="admin/stickers.html",
        context={
            "page_title": "Доска стикеров — Админ-панель",
            "active_section": "stickers",
            "current_user": current_user,
            "stickers": stickers,
            "palette": STICKER_PALETTE,
            "flash_message": None,
            "flash_type": "success",
        },
    )
    _ensure_csrf_cookie(request, response)
    return response


@router.get(
    "/stickers",
    response_model=list[StickerOut],
    summary="Список стикеров на доске (только админ)",
)
async def api_list_stickers(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[StickerOut]:
    return await list_stickers(session)


@router.post(
    "/stickers",
    response_model=StickerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создать стикер (только админ)",
)
async def api_create_sticker(
    payload: StickerCreate,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> StickerOut:
    return await create_sticker(session, admin.id, payload)


@router.patch(
    "/stickers/{sticker_id}",
    response_model=StickerOut,
    summary="Обновить позицию, текст или цвет стикера (только админ)",
)
async def api_update_sticker(
    sticker_id: int,
    payload: StickerUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> StickerOut:
    try:
        return await update_sticker(session, sticker_id, payload)
    except StickerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/stickers/{sticker_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить стикер (только админ)",
)
async def api_delete_sticker(
    sticker_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(verify_csrf_if_cookie_present)],
) -> None:
    try:
        await delete_sticker(session, sticker_id)
    except StickerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
