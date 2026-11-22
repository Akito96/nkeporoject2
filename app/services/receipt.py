from io import BytesIO
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.schemas.orders import OrderOut

CAFE_NAME = "Кофейня «Зерно и Пар»"
CAFE_SUBTITLE = "Свежая обжарка каждый день"

STATUS_LABELS: dict[str, str] = {
    "new": "Новый",
    "paid": "Оплачен",
    "done": "Выполнен",
    "cancelled": "Отменён",
}

FONT_REGULAR = "ReceiptRegular"
FONT_BOLD = "ReceiptBold"

_FONT_CANDIDATES: list[tuple[Path, Path]] = [
    (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ),
    (
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ),
    (
        Path("C:/Windows/Fonts/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
    ),
    (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ),
]


def _resolve_fonts() -> tuple[str, str]:
    """Регистрирует TrueType-шрифты с поддержкой кириллицы и возвращает их имена."""
    registered = set(pdfmetrics.getRegisteredFontNames())
    if FONT_REGULAR in registered and FONT_BOLD in registered:
        return FONT_REGULAR, FONT_BOLD

    for regular_path, bold_path in _FONT_CANDIDATES:
        if regular_path.exists():
            pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(regular_path)))
            if bold_path.exists():
                pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold_path)))
                return FONT_REGULAR, FONT_BOLD
            return FONT_REGULAR, FONT_REGULAR

    return "Helvetica", "Helvetica-Bold"


def _draw_qr_code(pdf: canvas.Canvas, payload: str, x: float, y: float, size: float) -> None:
    widget = qr.QrCodeWidget(payload)
    min_x, min_y, max_x, max_y = widget.getBounds()
    width = max_x - min_x
    height = max_y - min_y
    drawing = Drawing(
        size,
        size,
        transform=[size / width, 0, 0, size / height, 0, 0],
    )
    drawing.add(widget)
    renderPDF.draw(drawing, pdf, x, y)


def _truncate_text(text: str, max_chars: int = 34) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


def generate_order_receipt_pdf(
    order: OrderOut,
    *,
    customer_email: str | None = None,
) -> bytes:
    """Генерирует PDF-чек заказа с кириллицей, таблицей позиций, итогом и QR-кодом."""
    regular_font, bold_font = _resolve_fonts()

    buffer = BytesIO()
    page_width, page_height = A5
    pdf = canvas.Canvas(buffer, pagesize=A5)
    pdf.setTitle(f"Чек заказа №{order.id}")

    margin_x = 14 * mm
    right_x = page_width - margin_x
    y = page_height - 16 * mm

    accent_color = colors.HexColor("#8C4A27")
    text_color = colors.HexColor("#2C1E16")
    muted_color = colors.HexColor("#6B5344")
    border_color = colors.HexColor("#E3D5C5")

    # Шапка кофейни
    pdf.setFillColor(accent_color)
    pdf.setFont(bold_font, 15)
    pdf.drawString(margin_x, y, CAFE_NAME)
    y -= 5.5 * mm

    pdf.setFillColor(muted_color)
    pdf.setFont(regular_font, 9)
    pdf.drawString(margin_x, y, CAFE_SUBTITLE)
    y -= 6 * mm

    pdf.setStrokeColor(border_color)
    pdf.setLineWidth(1)
    pdf.line(margin_x, y, right_x, y)
    y -= 8 * mm

    # Информация о заказе
    pdf.setFillColor(text_color)
    pdf.setFont(bold_font, 12)
    pdf.drawString(margin_x, y, f"Чек по заказу №{order.id}")
    y -= 6 * mm

    pdf.setFont(regular_font, 9.5)
    pdf.drawString(margin_x, y, f"Дата: {order.created_at.strftime('%d.%m.%Y %H:%M')}")
    status_label = STATUS_LABELS.get(order.status.value, order.status.value)
    pdf.drawRightString(right_x, y, f"Статус: {status_label}")
    y -= 5.5 * mm

    if customer_email:
        pdf.setFillColor(muted_color)
        pdf.drawString(margin_x, y, f"Гость: {customer_email}")
        y -= 6 * mm

    pdf.setStrokeColor(border_color)
    pdf.line(margin_x, y, right_x, y)
    y -= 6 * mm

    # Заголовок таблицы позиций
    col_qty_x = right_x - 42 * mm
    col_price_x = right_x - 22 * mm

    pdf.setFillColor(muted_color)
    pdf.setFont(bold_font, 8.5)
    pdf.drawString(margin_x, y, "Позиция")
    pdf.drawRightString(col_qty_x, y, "Кол-во")
    pdf.drawRightString(col_price_x, y, "Цена")
    pdf.drawRightString(right_x, y, "Сумма")
    y -= 5 * mm

    pdf.setStrokeColor(border_color)
    pdf.setLineWidth(0.5)
    pdf.line(margin_x, y, right_x, y)
    y -= 5.5 * mm

    # Строки позиций
    pdf.setFillColor(text_color)
    pdf.setFont(regular_font, 9)
    for item in order.items:
        if y < 52 * mm:
            pdf.showPage()
            y = page_height - 18 * mm
            pdf.setFillColor(text_color)
            pdf.setFont(regular_font, 9)

        pdf.drawString(margin_x, y, _truncate_text(item.product_name))
        pdf.drawRightString(col_qty_x, y, f"{item.quantity} шт.")
        pdf.drawRightString(col_price_x, y, f"{item.price:.2f} ₽")
        pdf.drawRightString(right_x, y, f"{item.subtotal:.2f} ₽")
        y -= 6 * mm

    # Итог
    y -= 2 * mm
    pdf.setStrokeColor(accent_color)
    pdf.setLineWidth(1)
    pdf.line(margin_x, y, right_x, y)
    y -= 7 * mm

    pdf.setFillColor(text_color)
    pdf.setFont(bold_font, 11.5)
    pdf.drawString(margin_x, y, "ИТОГО К ОПЛАТЕ:")
    pdf.setFillColor(accent_color)
    pdf.drawRightString(right_x, y, f"{order.total:.2f} ₽")
    y -= 10 * mm

    # QR-код с номером заказа
    qr_size = 28 * mm
    if y - qr_size < 16 * mm:
        pdf.showPage()
        y = page_height - 20 * mm

    qr_x = (page_width - qr_size) / 2
    qr_y = y - qr_size
    qr_payload = f"ORDER-{order.id}"
    _draw_qr_code(pdf, qr_payload, qr_x, qr_y, qr_size)

    pdf.setFillColor(muted_color)
    pdf.setFont(regular_font, 8.5)
    pdf.drawCentredString(page_width / 2, qr_y - 4.5 * mm, f"Код заказа: {qr_payload}")
    pdf.drawCentredString(page_width / 2, qr_y - 9.5 * mm, "Спасибо за заказ! Ждём вас снова.")

    pdf.save()
    return buffer.getvalue()
