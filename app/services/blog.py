import re
from datetime import UTC, datetime
from math import ceil

import markdown
import nh3
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blog import Post
from app.schemas.blog import PostCreate, PostOut, PostUpdate


class PostSlugExistsError(Exception):
    """Пост с таким slug уже существует."""


class PostNotFoundError(Exception):
    """Пост не найден."""


_CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_ALLOWED_HTML_TAGS: set[str] = {
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "b", "em", "i", "u", "s", "del",
    "ul", "ol", "li",
    "blockquote", "pre", "code",
    "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
}

_ALLOWED_HTML_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
}

_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def slugify_title(title: str) -> str:
    """Генерирует URL-безопасный slug из заголовка (поддерживает кириллицу)."""
    transliterated = "".join(
        _CYRILLIC_TO_LATIN.get(ch, ch) for ch in title.strip().lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    return slug[:200] or "post"


def render_markdown_safe(body_md: str) -> str:
    """Рендерит Markdown в HTML на сервере и очищает результат от XSS-векторов."""
    raw_html = markdown.markdown(
        body_md,
        extensions=["fenced_code", "tables", "nl2br"],
    )
    return nh3.clean(
        raw_html,
        tags=_ALLOWED_HTML_TAGS,
        attributes=_ALLOWED_HTML_ATTRIBUTES,
        url_schemes={"http", "https"},
        link_rel="noopener noreferrer",
        strip_comments=True,
    )


def build_excerpt(body_html: str, max_length: int = 160) -> str:
    plain = _WHITESPACE_RE.sub(" ", _TAG_STRIP_RE.sub(" ", body_html)).strip()
    if len(plain) <= max_length:
        return plain
    return f"{plain[: max_length - 1].rstrip()}…"


def serialize_post(post: Post) -> PostOut:
    body_html = render_markdown_safe(post.body_md)
    return PostOut(
        id=post.id,
        title=post.title,
        slug=post.slug,
        cover=post.cover,
        body_md=post.body_md,
        body_html=body_html,
        excerpt=build_excerpt(body_html),
        is_published=post.is_published,
        published_at=post.published_at,
        created_at=post.created_at,
    )


def calculate_blog_pages(total: int, per_page: int) -> int:
    if total <= 0:
        return 1
    return ceil(total / per_page)


async def list_posts(
    session: AsyncSession,
    *,
    published_only: bool = True,
    page: int = 1,
    per_page: int = 6,
) -> tuple[list[PostOut], int]:
    query = select(Post)
    count_query = select(func.count(Post.id))

    if published_only:
        query = query.where(Post.is_published.is_(True))
        count_query = count_query.where(Post.is_published.is_(True))

    query = query.order_by(
        Post.published_at.desc().nullslast(),
        Post.created_at.desc(),
        Post.id.desc(),
    )

    total = int(await session.scalar(count_query) or 0)
    offset = (page - 1) * per_page
    result = await session.scalars(query.offset(offset).limit(per_page))
    return [serialize_post(post) for post in result.all()], total


async def get_post_by_slug(
    session: AsyncSession,
    slug: str,
    *,
    published_only: bool = True,
) -> Post | None:
    query = select(Post).where(Post.slug == slug.strip().lower())
    if published_only:
        query = query.where(Post.is_published.is_(True))
    return await session.scalar(query)


async def get_post_by_id(session: AsyncSession, post_id: int) -> Post | None:
    return await session.scalar(select(Post).where(Post.id == post_id))


async def create_post(session: AsyncSession, payload: PostCreate) -> PostOut:
    slug = payload.slug or slugify_title(payload.title)
    existing = await session.scalar(select(Post).where(Post.slug == slug))
    if existing is not None:
        raise PostSlugExistsError(f"Пост со slug «{slug}» уже существует")

    published_at = payload.published_at
    if payload.is_published and published_at is None:
        published_at = datetime.now(UTC)

    post = Post(
        title=payload.title,
        slug=slug,
        cover=payload.cover,
        body_md=payload.body_md,
        is_published=payload.is_published,
        published_at=published_at,
    )
    session.add(post)
    await session.commit()
    await session.refresh(post)
    return serialize_post(post)


async def update_post(
    session: AsyncSession,
    post_id: int,
    payload: PostUpdate,
) -> PostOut:
    post = await get_post_by_id(session, post_id)
    if post is None:
        raise PostNotFoundError("Пост не найден")

    updates = payload.model_dump(exclude_unset=True)

    if "slug" in updates and updates["slug"] is not None:
        new_slug = updates["slug"]
        if new_slug != post.slug:
            existing = await session.scalar(select(Post).where(Post.slug == new_slug))
            if existing is not None:
                raise PostSlugExistsError(f"Пост со slug «{new_slug}» уже существует")
            post.slug = new_slug

    if "title" in updates and updates["title"] is not None:
        post.title = updates["title"]
    if "cover" in updates:
        post.cover = updates["cover"]
    if "body_md" in updates and updates["body_md"] is not None:
        post.body_md = updates["body_md"]
    if "is_published" in updates and updates["is_published"] is not None:
        post.is_published = updates["is_published"]
    if "published_at" in updates:
        post.published_at = updates["published_at"]

    if post.is_published and post.published_at is None:
        post.published_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(post)
    return serialize_post(post)


async def delete_post(session: AsyncSession, post_id: int) -> None:
    post = await get_post_by_id(session, post_id)
    if post is None:
        raise PostNotFoundError("Пост не найден")

    await session.delete(post)
    await session.commit()
