from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


async def check_database_health(session: AsyncSession) -> bool:
    """Проверяет доступность PostgreSQL простым запросом SELECT 1."""
    try:
        result = await session.execute(text("SELECT 1"))
        return result.scalar_one() == 1
    except (SQLAlchemyError, OSError):
        return False
