import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

STICKER_PALETTE: list[tuple[str, str]] = [
    ("#FFF3B0", "Лимонный"),
    ("#FFD6A5", "Персиковый"),
    ("#CAFFBF", "Мятный"),
    ("#BDE0FE", "Небесный"),
    ("#E4C1F9", "Лавандовый"),
]


def _validate_color(value: str) -> str:
    cleaned = value.strip().upper()
    if not HEX_COLOR_RE.match(cleaned):
        raise ValueError("Цвет должен быть в формате HEX, например #FFF3B0")
    return cleaned


class StickerCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    color: str = Field(default="#FFF3B0")
    x: int = Field(default=24, ge=0, le=5000)
    y: int = Field(default=24, ge=0, le=5000)
    z: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Текст стикера не может быть пустым")
        return cleaned

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        return _validate_color(value)


class StickerUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    color: str | None = Field(default=None)
    x: int | None = Field(default=None, ge=0, le=5000)
    y: int | None = Field(default=None, ge=0, le=5000)
    z: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Текст стикера не может быть пустым")
        return cleaned

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_color(value)


class StickerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_id: int
    text: str
    color: str
    x: int
    y: int
    z: int
    created_at: datetime
