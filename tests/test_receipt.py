from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.models.order import OrderStatus
from app.schemas.orders import OrderItemOut, OrderOut
from app.services.receipt import generate_order_receipt_pdf
from tests.test_cart_orders import _auth_cookie, _make_fixture


def test_generate_order_receipt_pdf_returns_valid_pdf_bytes() -> None:
    order = OrderOut(
        id=42,
        user_id=1,
        status=OrderStatus.PAID,
        total=Decimal("790.00"),
        created_at=datetime(2026, 11, 22, 14, 30, tzinfo=UTC),
        items=[
            OrderItemOut(
                id=1,
                product_id=1,
                product_name="Капучино",
                quantity=2,
                price=Decimal("260.00"),
                subtotal=Decimal("520.00"),
            ),
            OrderItemOut(
                id=2,
                product_id=2,
                product_name="Миндальный круассан",
                quantity=1,
                price=Decimal("270.00"),
                subtotal=Decimal("270.00"),
            ),
        ],
    )

    pdf_bytes = generate_order_receipt_pdf(order, customer_email="guest@coffee.local")

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes
    assert len(pdf_bytes) > 500


@pytest.mark.asyncio
async def test_receipt_endpoint_permissions_and_headers() -> None:
    app, _, user1, user2, admin, _ = _make_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Создаём заказ от имени user1
        client.cookies.update(_auth_cookie(user1))
        await client.post("/cart/items", json={"product_id": 1, "quantity": 2})
        order_id = (await client.post("/orders")).json()["id"]

        # Владелец получает PDF-чек
        owner_resp = await client.get(f"/orders/{order_id}/receipt")
        assert owner_resp.status_code == 200
        assert owner_resp.headers["content-type"] == "application/pdf"
        assert f'filename="receipt-order-{order_id}.pdf"' in owner_resp.headers[
            "content-disposition"
        ]
        assert owner_resp.content.startswith(b"%PDF-")

        # Администратор также может скачать чек чужого заказа
        client.cookies.update(_auth_cookie(admin))
        admin_resp = await client.get(f"/orders/{order_id}/receipt")
        assert admin_resp.status_code == 200
        assert admin_resp.content.startswith(b"%PDF-")

        # Другой пользователь получает 403
        client.cookies.update(_auth_cookie(user2))
        other_resp = await client.get(f"/orders/{order_id}/receipt")
        assert other_resp.status_code == 403

        # Несуществующий заказ -> 404
        missing_resp = await client.get("/orders/9999/receipt")
        assert missing_resp.status_code == 404

        # Без авторизации -> 401
        client.cookies.clear()
        anon_resp = await client.get(f"/orders/{order_id}/receipt")
        assert anon_resp.status_code == 401


@pytest.mark.asyncio
async def test_order_pages_contain_download_receipt_button() -> None:
    app, _, user1, _, _, _ = _make_fixture()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=_auth_cookie(user1),
    ) as client:
        await client.post("/cart/items", json={"product_id": 1, "quantity": 1})
        order_id = (await client.post("/orders")).json()["id"]

        list_html = await client.get("/orders", headers={"Accept": "text/html"})
        assert list_html.status_code == 200
        assert f"/orders/{order_id}/receipt" in list_html.text
        assert "Скачать чек" in list_html.text

        detail_html = await client.get(
            f"/orders/{order_id}",
            headers={"Accept": "text/html"},
        )
        assert detail_html.status_code == 200
        assert f"/orders/{order_id}/receipt" in detail_html.text
        assert "Скачать чек" in detail_html.text
