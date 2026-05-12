import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Pattern(Base):
    __tablename__ = "patterns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    garment_type: Mapped[str | None] = mapped_column(String, nullable=True)

    # Denormalized metadata for filtering without parsing the geometry blob
    piece_count: Mapped[int] = mapped_column(Integer, default=0)
    waist_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    hip_cm: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    # Full .psnap document stored as JSON; maps to JSONB on PostgreSQL
    geometry: Mapped[dict] = mapped_column(JSON, nullable=False)
