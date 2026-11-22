from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import create_app
from app.models.blog import Post
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password
from app.services.blog import render_markdown_safe, slugify_title


class _ScalarList:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class InMemoryBlogSession:
    """In-memory async-сессия для тестов блога."""

    def __init__(self, users: list[User], posts: list[Post]) -> None:
        self.users = list(users)
        self.posts = list(posts)
        self._next_post_id = max((p.id for p in self.posts), default=0) + 1

    async def scalar(self, stmt: Any) -> Any:
        compiled = stmt.compile()
        sql = str(compiled)
        params = compiled.params

        if "FROM users" in sql:
            if "id_1" in params:
                return next((u for u in self.users if u.id == params["id_1"]), None)
            if "email_1" in params:
                return next((u for u in self.users if u.email == params["email_1"]), None)

        if "count(posts.id)" in sql.lower():
            items = self._filter_posts(sql)
            return len(items)

        if "FROM posts" in sql:
            if "slug_1" in params:
                slug = params["slug_1"]
                pub_only = "is_published IS true" in sql
                return next(
                    (
                        p
                        for p in self.posts
                        if p.slug == slug and (not pub_only or p.is_published)
                    ),
                    None,
                )
            if "id_1" in params:
                pid = params["id_1"]
                return next((p for p in self.posts if p.id == pid), None)

        return None

    def _filter_posts(self, sql: str) -> list[Post]:
        items = list(self.posts)
        if "is_published IS true" in sql:
            items = [p for p in items if p.is_published]
        items.sort(
            key=lambda p: (
                p.published_at is not None,
                p.published_at or datetime.min.replace(tzinfo=UTC),
                p.created_at,
                p.id,
            ),
            reverse=True,
        )
        return items

    async def scalars(self, stmt: Any) -> _ScalarList:
        compiled = stmt.compile()
        sql = str(compiled)
        params = compiled.params

        if "FROM posts" in sql:
            items = self._filter_posts(sql)
            offset = int(params.get("param_2", 0) or 0)
            limit = int(params.get("param_1", len(items)) or len(items))
            return _ScalarList(items[offset : offset + limit])

        return _ScalarList([])

    def add(self, obj: Post) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_post_id
            self._next_post_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)
        self.posts.append(obj)

    async def delete(self, obj: Post) -> None:
        self.posts = [p for p in self.posts if p.id != obj.id]

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None


def _make_blog_fixture() -> tuple[FastAPI, InMemoryBlogSession, User, User]:
    user = User(
        id=1,
        email="user@coffee.local",
        password_hash=hash_password("UserPass123"),
        role=UserRole.USER.value,
        created_at=datetime.now(UTC),
    )
    admin = User(
        id=2,
        email="admin@coffee.local",
        password_hash=hash_password("AdminPass123"),
        role=UserRole.ADMIN.value,
        created_at=datetime.now(UTC),
    )
    now = datetime.now(UTC)
    posts = [
        Post(
            id=1,
            title="Первый пост",
            slug="first-post",
            cover="/static/img/post1.jpg",
            body_md="## Привет\n\n**Вкусный кофе**",
            is_published=True,
            published_at=now - timedelta(days=2),
            created_at=now - timedelta(days=2),
        ),
        Post(
            id=2,
            title="Второй пост",
            slug="second-post",
            cover=None,
            body_md="Рецепт V60",
            is_published=True,
            published_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
        ),
        Post(
            id=3,
            title="Секретный черновик",
            slug="secret-draft",
            cover=None,
            body_md="Ещё не готово",
            is_published=False,
            published_at=None,
            created_at=now,
        ),
    ]
    session = InMemoryBlogSession([user, admin], posts)
    app = create_app()

    async def override_get_db() -> AsyncGenerator[InMemoryBlogSession, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return app, session, user, admin


def _cookie(user: User) -> dict[str, str]:
    return {"access_token": create_access_token(user.id, user.role)}


def test_markdown_xss_sanitization_and_slugify() -> None:
    malicious_md = (
        "## Заголовок\n\n"
        "**Безопасный текст**\n\n"
        "<script>alert('xss')</script>\n"
        "<img src=x onerror=alert(1)>\n"
        "[Кликни](javascript:alert(2))\n"
        "[Сайт](https://example.com)"
    )
    rendered = render_markdown_safe(malicious_md)

    assert "<h2>Заголовок</h2>" in rendered
    assert "<strong>Безопасный текст</strong>" in rendered
    assert "<script" not in rendered.lower()
    assert "onerror" not in rendered.lower()
    assert "javascript:" not in rendered.lower()
    assert 'href="https://example.com"' in rendered
    assert 'rel="noopener noreferrer"' in rendered

    assert slugify_title("Гид по воронке V60!") == "gid-po-voronke-v60"


@pytest.mark.asyncio
async def test_public_blog_list_pagination_and_draft_hiding() -> None:
    app, _, user, admin = _make_blog_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Гость видит только опубликованные посты (2 из 3) с пагинацией
        resp = await client.get("/blog", params={"page": 1, "per_page": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["pages"] == 2
        assert len(body["items"]) == 1
        assert body["items"][0]["slug"] == "second-post"

        # Черновик недоступен гостю -> 404
        assert (await client.get("/blog/secret-draft")).status_code == 404

        # include_drafts запрещён обычному пользователю -> 403
        client.cookies.update(_cookie(user))
        assert (await client.get("/blog", params={"include_drafts": "true"})).status_code == 403

        # Админ может читать черновик и видеть все посты
        client.cookies.update(_cookie(admin))
        draft_resp = await client.get("/blog/secret-draft")
        assert draft_resp.status_code == 200
        assert draft_resp.json()["is_published"] is False

        all_resp = await client.get("/blog", params={"include_drafts": "true"})
        assert all_resp.status_code == 200
        assert all_resp.json()["total"] == 3


@pytest.mark.asyncio
async def test_admin_blog_crud_and_permissions() -> None:
    app, _, user, admin = _make_blog_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Гость -> 401
        unauth = await client.post(
            "/blog",
            json={"title": "Новый пост", "body_md": "Текст"},
        )
        assert unauth.status_code == 401

        # Обычный пользователь -> 403
        client.cookies.update(_cookie(user))
        forbid = await client.post(
            "/blog",
            json={"title": "Новый пост", "body_md": "Текст"},
        )
        assert forbid.status_code == 403

        # Админ создаёт пост с автогенерацией slug
        client.cookies.update(_cookie(admin))
        created = await client.post(
            "/blog",
            json={
                "title": "Новый рецепт эспрессо",
                "body_md": "## Шаг 1\n\n<script>bad()</script>Смелите зерно.",
                "is_published": True,
            },
        )
        assert created.status_code == 201
        post = created.json()
        assert post["slug"] == "novyy-retsept-espresso"
        assert post["published_at"] is not None
        assert "<script" not in post["body_html"].lower()

        # Дубликат slug -> 409
        dup = await client.post(
            "/blog",
            json={
                "title": "Другой",
                "slug": "novyy-retsept-espresso",
                "body_md": "Текст",
            },
        )
        assert dup.status_code == 409

        # Редактирование поста
        updated = await client.patch(
            f"/blog/{post['id']}",
            json={"title": "Обновлённый рецепт", "is_published": False},
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Обновлённый рецепт"
        assert updated.json()["is_published"] is False

        # Удаление поста
        deleted = await client.delete(f"/blog/{post['id']}")
        assert deleted.status_code == 204
        assert (await client.get(f"/blog/{post['slug']}")).status_code == 404


@pytest.mark.asyncio
async def test_blog_html_pages() -> None:
    app, _, _, admin = _make_blog_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        list_html = await client.get("/blog", headers={"Accept": "text/html"})
        assert list_html.status_code == 200
        assert "Блог кофейни" in list_html.text
        assert "Первый пост" in list_html.text

        detail_html = await client.get("/blog/first-post", headers={"Accept": "text/html"})
        assert detail_html.status_code == 200
        assert "<strong>Вкусный кофе</strong>" in detail_html.text

        # Гость на /blog/admin -> редирект на /auth/login
        guest_admin = await client.get("/blog/admin", headers={"Accept": "text/html"})
        assert guest_admin.status_code == 302

        # Админ открывает /blog/admin
        client.cookies.update(_cookie(admin))
        admin_html = await client.get("/blog/admin", headers={"Accept": "text/html"})
        assert admin_html.status_code == 200
        assert "Управление блогом" in admin_html.text
