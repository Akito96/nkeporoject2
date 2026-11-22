from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.blog import router as blog_router
from app.api.cart import router as cart_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.config import get_settings
from app.database import engine, get_db
from app.schemas.health import HealthResponse
from app.services.health import check_database_health

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Coffee Shop",
        debug=settings.debug,
        lifespan=lifespan,
    )

    static_dir = BASE_DIR / "static"
    if static_dir.exists():
        application.mount("/static", StaticFiles(directory=static_dir), name="static")

    application.include_router(auth_router)
    application.include_router(products_router)
    application.include_router(cart_router)
    application.include_router(orders_router)
    application.include_router(blog_router)
    application.include_router(admin_router)

    @application.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/products", status_code=status.HTTP_302_FOUND)

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["system"],
        summary="Проверка состояния приложения и БД",
    )
    async def healthcheck(
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> JSONResponse:
        db_ok = await check_database_health(session)
        payload = HealthResponse(
            status="ok" if db_ok else "degraded",
            database="ok" if db_ok else "unavailable",
        )
        http_status = (
            status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return JSONResponse(status_code=http_status, content=payload.model_dump())

    return application


app = create_app()
