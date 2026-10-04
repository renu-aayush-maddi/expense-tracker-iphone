import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SecurityEvent(Base):
    """Authentication and security events (logins, failures, lockouts, blocked
    requests, suspicious patterns). Kept separate from the admin audit log."""

    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_created_at", "created_at"),
        Index("ix_security_events_user", "user_id", "created_at"),
        Index("ix_security_events_ip", "ip_address", "created_at"),
        Index("ix_security_events_type", "event_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="info")  # info | warning | critical
    success: Mapped[bool | None] = mapped_column(Boolean)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # no FK: history survives user changes
    email: Mapped[str | None] = mapped_column(String(255))  # the email that was attempted
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    reason: Mapped[str | None] = mapped_column(String(200))
    details: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
