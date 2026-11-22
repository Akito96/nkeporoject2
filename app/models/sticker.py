from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class Sticker(Base):
    __tablename__ = "stickers"
    __table_args__ = (
        CheckConstraint("z >= 0", name="sticker_z_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(
        String(20),
        default="#FFF3B0",
        server_default="#FFF3B0",
        nullable=False,
    )
    x: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    y: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    z: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    author: Mapped[User] = relationship(back_populates="stickers")
