"""External channel (Tag today, other channels later)."""


from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class Channel(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("channel_type", "external_channel_id", name="uq_channel"),
    )

    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
