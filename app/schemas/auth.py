import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import UserRole

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_and_normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 255 or not EMAIL_REGEX.match(normalized) or ".." in normalized:
        raise ValueError("Введите корректный адрес электронной почты")
    return normalized


class UserRegister(BaseModel):
    email: str = Field(..., description="Электронная почта пользователя")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Пароль длиной не менее 8 символов",
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_and_normalize_email(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("Пароль не может состоять только из пробелов")
        return value


class UserLogin(BaseModel):
    email: str = Field(..., description="Электронная почта пользователя")
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_and_normalize_email(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: UserRole
    created_at: datetime
