import uuid
from pathlib import Path

ALLOWED_IMAGE_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 МБ

DEFAULT_UPLOADS_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads"


class InvalidImageTypeError(Exception):
    """Недопустимый формат изображения."""


class ImageTooLargeError(Exception):
    """Превышен максимально допустимый размер изображения."""


def _detect_image_extension(data: bytes) -> str | None:
    """Определяет формат по сигнатуре (magic bytes), чтобы защититься от подмены Content-Type."""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def save_uploaded_image(
    data: bytes,
    content_type: str | None,
    *,
    upload_dir: Path | None = None,
) -> tuple[str, str, int]:
    """Валидирует тип, сигнатуру и размер файла, сохраняет под случайным именем."""
    if not content_type or content_type.lower() not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise InvalidImageTypeError(
            "Допускаются только изображения JPEG, PNG или WebP"
        )

    size = len(data)
    if size == 0:
        raise InvalidImageTypeError("Загруженный файл пуст")
    if size > MAX_IMAGE_SIZE_BYTES:
        raise ImageTooLargeError("Размер файла превышает максимально допустимые 5 МБ")

    detected_ext = _detect_image_extension(data)
    expected_ext = ALLOWED_IMAGE_CONTENT_TYPES[content_type.lower()]
    if detected_ext is None or detected_ext != expected_ext:
        raise InvalidImageTypeError(
            "Содержимое файла не соответствует заявленному типу изображения"
        )

    target_dir = upload_dir or DEFAULT_UPLOADS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{detected_ext}"
    file_path = target_dir / filename
    file_path.write_bytes(data)

    return f"/static/uploads/{filename}", filename, size
