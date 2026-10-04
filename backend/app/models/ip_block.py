import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IpBlock(Base):
    """An IP address blocked by an admin. Unblocking keeps the row (history)."""

    __tablename__ = "ip_blocks"
    __table_args__ = (Index("ix_ip_blocks_ip_active", "ip_address", "unblocked_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    blocked_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    blocked_by_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # None = until unblocked
    unblocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unblocked_by_email: Mapped[str | None] = mapped_column(String(255))
