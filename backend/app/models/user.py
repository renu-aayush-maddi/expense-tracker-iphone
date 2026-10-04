import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Account status values
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"  # turned off (e.g. on request); reversible
STATUS_SUSPENDED = "suspended"  # temporary hold
STATUS_BLOCKED = "blocked"  # security/abuse block
STATUS_DELETED = "deleted"  # soft-deleted by a super admin; data kept
USER_STATUSES = [STATUS_ACTIVE, STATUS_DISABLED, STATUS_SUSPENDED, STATUS_BLOCKED, STATUS_DELETED]


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_created_at", "created_at"),
        Index("ix_users_last_activity_at", "last_activity_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # Authorization: "user" | "read_only_admin" | "admin" | "super_admin" (see core/permissions.py).
    # Never set from request data except through the super-admin role endpoint.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default="user", index=True)

    # Account status and who changed it last.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_ACTIVE, server_default=STATUS_ACTIVE, index=True
    )
    status_reason: Mapped[str | None] = mapped_column(Text)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    status_changed_by_email: Mapped[str | None] = mapped_column(String(255))  # kept even if that admin is removed
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Security bookkeeping (only what's needed for account security).
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_ip: Mapped[str | None] = mapped_column(String(45))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[str | None] = mapped_column(String(45))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
