import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG_REGEX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _normalize_optional_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if not (
        cleaned.startswith("/")
        or cleaned.startswith("http://")
        or cleaned.startswith("https://")
    ):
        raise ValueError("Обложка должна быть относительным путём или URL (http/https)")
    return cleaned


def _validate_optional_slug(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if len(normalized) > 200 or not SLUG_REGEX.match(normalized):
        raise ValueError(
            "Slug может содержать только строчные латинские буквы, цифры и дефисы"
        )
    return normalized


class PostCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    slug: str | None = Field(default=None, max_length=200)
    cover: str | None = Field(default=None, max_length=500)
    body_md: str = Field(..., min_length=1)
    is_published: bool = False
    published_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Заголовок должен содержать минимум 3 символа")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        return _validate_optional_slug(value)

    @field_validator("cover")
    @classmethod
    def validate_cover(cls, value: str | None) -> str | None:
        return _normalize_optional_url(value)


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    slug: str | None = Field(default=None, max_length=200)
    cover: str | None = Field(default=None, max_length=500)
    body_md: str | None = Field(default=None, min_length=1)
    is_published: bool | None = None
    published_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Заголовок должен содержать минимум 3 символа")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        return _validate_optional_slug(value)

    @field_validator("cover")
    @classmethod
    def validate_cover(cls, value: str | None) -> str | None:
        return _normalize_optional_url(value)


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    cover: str | None
    body_md: str
    body_html: str
    excerpt: str
    is_published: bool
    published_at: datetime | None
    created_at: datetime


class PostListResponse(BaseModel):
    items: list[PostOut]
    total: int
    page: int
    per_page: int
    pages: int
