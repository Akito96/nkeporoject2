import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, engine
from app.models import Category, Post, Product, User, UserRole
from app.services.auth import hash_password


class SeedUser(TypedDict):
    email: str
    password: str
    role: UserRole


class SeedCategory(TypedDict):
    name: str
    slug: str


class SeedProduct(TypedDict):
    category_slug: str
    name: str
    description: str
    price: Decimal
    image: str | None
    stock: int
    is_active: bool


class SeedPost(TypedDict):
    title: str
    slug: str
    cover: str | None
    body_md: str
    is_published: bool
    days_ago: int


SEED_USERS: list[SeedUser] = [
    {
        "email": "admin@coffee.local",
        "password": "AdminPassword123!",
        "role": UserRole.ADMIN,
    },
    {
        "email": "user@coffee.local",
        "password": "UserPassword123!",
        "role": UserRole.USER,
    },
]

SEED_CATEGORIES: list[SeedCategory] = [
    {"name": "Классический кофе", "slug": "classic-coffee"},
    {"name": "Авторские напитки", "slug": "signature-drinks"},
    {"name": "Десерты", "slug": "desserts"},
    {"name": "Зёрна и аксессуары", "slug": "beans-and-gear"},
]

SEED_PRODUCTS: list[SeedProduct] = [
    # Классический кофе (4)
    {
        "category_slug": "classic-coffee",
        "name": "Эспрессо",
        "description": (
            "Плотный шот 100% арабики Эфиопия Иргачеффе с нотами бергамота и тёмного шоколада."
        ),
        "price": Decimal("180.00"),
        "image": "/static/img/espresso.jpg",
        "stock": 50,
        "is_active": True,
    },
    {
        "category_slug": "classic-coffee",
        "name": "Американо",
        "description": (
            "Двойной эспрессо с горячей фильтрованной водой. Мягкий и сбалансированный вкус."
        ),
        "price": Decimal("210.00"),
        "image": "/static/img/americano.jpg",
        "stock": 50,
        "is_active": True,
    },
    {
        "category_slug": "classic-coffee",
        "name": "Капучино",
        "description": "Эспрессо и бархатная молочная пена в идеальной пропорции.",
        "price": Decimal("260.00"),
        "image": "/static/img/cappuccino.jpg",
        "stock": 45,
        "is_active": True,
    },
    {
        "category_slug": "classic-coffee",
        "name": "Флэт Уайт",
        "description": (
            "Двойной ристретто и тонкий слой глянцевого молока для насыщенного кофейного вкуса."
        ),
        "price": Decimal("290.00"),
        "image": "/static/img/flat-white.jpg",
        "stock": 40,
        "is_active": True,
    },
    # Авторские напитки (4)
    {
        "category_slug": "signature-drinks",
        "name": "Лавандовый раф",
        "description": "Нежный сливочный раф с натуральным сиропом крымской лаванды и ванилью.",
        "price": Decimal("340.00"),
        "image": "/static/img/lavender-raf.jpg",
        "stock": 30,
        "is_active": True,
    },
    {
        "category_slug": "signature-drinks",
        "name": "Солёная карамель латте",
        "description": "Латте на основе домашней карамели с хлопьями морской соли.",
        "price": Decimal("330.00"),
        "image": "/static/img/salted-caramel-latte.jpg",
        "stock": 35,
        "is_active": True,
    },
    {
        "category_slug": "signature-drinks",
        "name": "Бамбл-кофе",
        "description": (
            "Слоистый освежающий напиток из свежевыжатого апельсинового сока, карамели и эспрессо."
        ),
        "price": Decimal("350.00"),
        "image": "/static/img/bumble.jpg",
        "stock": 25,
        "is_active": True,
    },
    {
        "category_slug": "signature-drinks",
        "name": "Матча-тоник юдзу",
        "description": (
            "Японская церемониальная матча со льдом, тоником и цитрусовым акцентом юдзу."
        ),
        "price": Decimal("360.00"),
        "image": "/static/img/matcha-tonic.jpg",
        "stock": 20,
        "is_active": True,
    },
    # Десерты (4)
    {
        "category_slug": "desserts",
        "name": "Миндальный круассан",
        "description": (
            "Хрустящий слоёный круассан с миндальным кремом франжипан и лепестками миндаля."
        ),
        "price": Decimal("270.00"),
        "image": "/static/img/almond-croissant.jpg",
        "stock": 18,
        "is_active": True,
    },
    {
        "category_slug": "desserts",
        "name": "Баскский чизкейк",
        "description": (
            "Карамелизованная корочка и нежнейшая сливочная середина из творожного сыра."
        ),
        "price": Decimal("380.00"),
        "image": "/static/img/basque-cheesecake.jpg",
        "stock": 12,
        "is_active": True,
    },
    {
        "category_slug": "desserts",
        "name": "Шоколадный брауни с пеканом",
        "description": "Тёплый брауни на бельгийском тёмном шоколаде 70% с обжаренным пеканом.",
        "price": Decimal("290.00"),
        "image": "/static/img/brownie.jpg",
        "stock": 16,
        "is_active": True,
    },
    {
        "category_slug": "desserts",
        "name": "Кардамоновая булочка",
        "description": "Скандинавская сдобная булочка со свежемолотым зелёным кардамоном.",
        "price": Decimal("240.00"),
        "image": "/static/img/cardamom-bun.jpg",
        "stock": 22,
        "is_active": True,
    },
    # Зёрна и аксессуары (3)
    {
        "category_slug": "beans-and-gear",
        "name": "Зёрна Эфиопия Гуджи, 250 г",
        "description": (
            "Мытая обработка, светлая обжарка под фильтр. Вкус: жасмин, белый персик, лайм."
        ),
        "price": Decimal("950.00"),
        "image": "/static/img/espresso.jpg",
        "stock": 25,
        "is_active": True,
    },
    {
        "category_slug": "beans-and-gear",
        "name": "Зёрна Колумбия Уила, 250 г",
        "description": (
            "Средняя обжарка под эспрессо. Вкус: молочный шоколад, фундук и красное яблоко."
        ),
        "price": Decimal("890.00"),
        "image": "/static/img/americano.jpg",
        "stock": 30,
        "is_active": True,
    },
    {
        "category_slug": "beans-and-gear",
        "name": "Керамическая воронка V60-02",
        "description": "Классическая воронка для альтернативного заваривания на 1–4 чашки.",
        "price": Decimal("2450.00"),
        "image": "/static/img/flat-white.jpg",
        "stock": 10,
        "is_active": True,
    },
]

SEED_POSTS: list[SeedPost] = [
    {
        "title": "Как выбрать зерно для домашнего эспрессо",
        "slug": "how-to-choose-espresso-beans",
        "cover": "/static/img/espresso.jpg",
        "body_md": (
            "## На что смотреть на пачке\n\n"
            "При выборе зерна под эспрессо обращайте внимание на **дату обжарки** "
            "(оптимально от 7 до 30 дней) и профиль обжарки.\n\n"
            "- *Мытая обработка* даст чистую кислотность.\n"
            "- *Натуральная обработка* добавит сладости и ягодных нот.\n"
        ),
        "is_published": True,
        "days_ago": 10,
    },
    {
        "title": "Гид по завариванию в воронке V60",
        "slug": "v60-brewing-guide",
        "cover": "/static/img/flat-white.jpg",
        "body_md": (
            "## Базовый рецепт\n\n"
            "Используйте пропорцию **15 г кофе на 250 мл воды** температурой 93 °C.\n\n"
            "1. Промойте бумажный фильтр горячей водой.\n"
            "2. Сделайте предсмачивание (45 мл на 35 секунд).\n"
            "3. Влейте оставшуюся воду двумя плавными подходами до 2:45.\n"
        ),
        "is_published": True,
        "days_ago": 5,
    },
    {
        "title": "Сезонное меню: почему мы полюбили юдзу и лаванду",
        "slug": "seasonal-menu-yuzu-lavender",
        "cover": "/static/img/lavender-raf.jpg",
        "body_md": (
            "## Баланс вкуса в авторских напитках\n\n"
            "В новом сезоне мы отказались от промышленных сиропов и варим основы "
            "на собственной кухне из свежих ягод, цедры и специй.\n\n"
            "Попробуйте **матча-тоник юдзу** или **лавандовый раф** в нашей кофейне!\n"
        ),
        "is_published": True,
        "days_ago": 1,
    },
]


async def seed_database(session: AsyncSession) -> None:
    # 1. Пользователи (идемпотентно по email)
    for user_data in SEED_USERS:
        existing_user = await session.scalar(
            select(User).where(User.email == user_data["email"])
        )
        if existing_user is None:
            session.add(
                User(
                    email=user_data["email"],
                    password_hash=hash_password(user_data["password"]),
                    role=user_data["role"].value,
                )
            )

    # 2. Категории (идемпотентно по slug)
    categories_by_slug: dict[str, Category] = {}
    for cat_data in SEED_CATEGORIES:
        category = await session.scalar(
            select(Category).where(Category.slug == cat_data["slug"])
        )
        if category is None:
            category = Category(name=cat_data["name"], slug=cat_data["slug"])
            session.add(category)
            await session.flush()
        categories_by_slug[cat_data["slug"]] = category

    # 3. Товары (идемпотентно по category_id + name)
    for prod_data in SEED_PRODUCTS:
        category = categories_by_slug[prod_data["category_slug"]]
        existing_product = await session.scalar(
            select(Product).where(
                Product.category_id == category.id,
                Product.name == prod_data["name"],
            )
        )
        if existing_product is None:
            session.add(
                Product(
                    category_id=category.id,
                    name=prod_data["name"],
                    description=prod_data["description"],
                    price=prod_data["price"],
                    image=prod_data["image"],
                    stock=prod_data["stock"],
                    is_active=prod_data["is_active"],
                )
            )
        elif existing_product.image != prod_data["image"]:
            existing_product.image = prod_data["image"]

    # 4. Посты блога (идемпотентно по slug)
    now = datetime.now(UTC)
    for post_data in SEED_POSTS:
        existing_post = await session.scalar(
            select(Post).where(Post.slug == post_data["slug"])
        )
        if existing_post is None:
            published_at = (
                now - timedelta(days=post_data["days_ago"])
                if post_data["is_published"]
                else None
            )
            session.add(
                Post(
                    title=post_data["title"],
                    slug=post_data["slug"],
                    cover=post_data["cover"],
                    body_md=post_data["body_md"],
                    is_published=post_data["is_published"],
                    published_at=published_at,
                )
            )
        elif existing_post.cover != post_data["cover"]:
            existing_post.cover = post_data["cover"]

    await session.commit()


async def main() -> None:
    try:
        async with async_session_factory() as session:
            await seed_database(session)
        print("Seed completed successfully.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
