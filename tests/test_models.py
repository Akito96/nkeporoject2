from decimal import Decimal

import bcrypt
from sqlalchemy import Numeric

from app.models import Base, OrderStatus, UserRole
from app.seed import SEED_CATEGORIES, SEED_POSTS, SEED_PRODUCTS, SEED_USERS, hash_password


def test_all_expected_tables_registered() -> None:
    expected_tables = {
        "users",
        "categories",
        "products",
        "carts",
        "cart_items",
        "orders",
        "order_items",
        "posts",
        "stickers",
    }
    assert expected_tables.issubset(set(Base.metadata.tables.keys()))


def test_money_columns_use_numeric_10_2() -> None:
    money_columns = [
        ("products", "price"),
        ("orders", "total"),
        ("order_items", "price"),
    ]
    for table_name, col_name in money_columns:
        col = Base.metadata.tables[table_name].c[col_name]
        assert isinstance(col.type, Numeric)
        assert col.type.precision == 10
        assert col.type.scale == 2


def test_all_foreign_keys_have_indexes() -> None:
    for table_name, table in Base.metadata.tables.items():
        indexed_columns = {
            tuple(col.name for col in idx.columns) for idx in table.indexes
        }
        for fk in table.foreign_keys:
            fk_col = (fk.parent.name,)
            assert fk_col in indexed_columns, (
                f"Внешний ключ {table_name}.{fk.parent.name} должен быть проиндексирован"
            )


def test_analytics_indexes_present() -> None:
    orders_indexes = {
        tuple(c.name for c in idx.columns)
        for idx in Base.metadata.tables["orders"].indexes
    }
    order_items_indexes = {
        tuple(c.name for c in idx.columns)
        for idx in Base.metadata.tables["order_items"].indexes
    }
    assert ("created_at",) in orders_indexes
    assert ("product_id",) in order_items_indexes


def test_enums_match_domain_values() -> None:
    assert {r.value for r in UserRole} == {"user", "admin"}
    assert {s.value for s in OrderStatus} == {"new", "paid", "done", "cancelled"}


def test_seed_dataset_counts_and_integrity() -> None:
    assert len(SEED_USERS) == 2
    assert {u["role"] for u in SEED_USERS} == {UserRole.ADMIN, UserRole.USER}
    assert len(SEED_CATEGORIES) == 4
    assert len(SEED_PRODUCTS) == 15
    assert len(SEED_POSTS) == 3

    category_slugs = {c["slug"] for c in SEED_CATEGORIES}
    assert len(category_slugs) == 4

    for product in SEED_PRODUCTS:
        assert product["category_slug"] in category_slugs
        assert isinstance(product["price"], Decimal)
        assert product["price"] > 0
        assert product["stock"] >= 0

    post_slugs = {p["slug"] for p in SEED_POSTS}
    assert len(post_slugs) == 3


def test_seed_password_hashing_uses_bcrypt() -> None:
    raw = "AdminPassword123!"
    hashed = hash_password(raw)
    assert hashed != raw
    assert bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
