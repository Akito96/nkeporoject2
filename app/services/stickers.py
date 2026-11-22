from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sticker import Sticker
from app.schemas.stickers import StickerCreate, StickerOut, StickerUpdate


class StickerNotFoundError(Exception):
    """Стикер не найден."""


async def list_stickers(session: AsyncSession) -> list[StickerOut]:
    result = await session.scalars(
        select(Sticker).order_by(Sticker.z.asc(), Sticker.id.asc())
    )
    return [StickerOut.model_validate(item) for item in result.all()]


async def create_sticker(
    session: AsyncSession,
    author_id: int,
    payload: StickerCreate,
) -> StickerOut:
    z_value = payload.z
    if z_value is None:
        max_z = int(await session.scalar(select(func.coalesce(func.max(Sticker.z), 0))) or 0)
        z_value = max_z + 1

    sticker = Sticker(
        author_id=author_id,
        text=payload.text,
        color=payload.color,
        x=payload.x,
        y=payload.y,
        z=z_value,
    )
    session.add(sticker)
    await session.commit()
    await session.refresh(sticker)
    return StickerOut.model_validate(sticker)


async def update_sticker(
    session: AsyncSession,
    sticker_id: int,
    payload: StickerUpdate,
) -> StickerOut:
    sticker = await session.scalar(select(Sticker).where(Sticker.id == sticker_id))
    if sticker is None:
        raise StickerNotFoundError("Стикер не найден")

    updates = payload.model_dump(exclude_unset=True)
    for field in ("text", "color", "x", "y", "z"):
        if field in updates and updates[field] is not None:
            setattr(sticker, field, updates[field])

    await session.commit()
    await session.refresh(sticker)
    return StickerOut.model_validate(sticker)


async def delete_sticker(session: AsyncSession, sticker_id: int) -> None:
    sticker = await session.scalar(select(Sticker).where(Sticker.id == sticker_id))
    if sticker is None:
        raise StickerNotFoundError("Стикер не найден")

    await session.delete(sticker)
    await session.commit()
