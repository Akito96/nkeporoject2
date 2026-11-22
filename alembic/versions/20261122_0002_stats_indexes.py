"""Add composite indexes for analytics queries.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22 22:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_orders_status_created_at",
        "orders",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_order_items_order_product",
        "order_items",
        ["order_id", "product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_order_items_order_product", table_name="order_items")
    op.drop_index("ix_orders_status_created_at", table_name="orders")
