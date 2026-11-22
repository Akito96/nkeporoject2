from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    debug: bool = True

    database_url: str = (
        "postgresql+asyncpg://coffee_user:change_me_in_production@db:5432/coffee_shop"
    )

    secret_key: str = "change_me_to_a_long_random_secret_key"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    access_token_cookie_name: str = "access_token"
    csrf_cookie_name: str = "csrf_token"
    cookie_secure: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
