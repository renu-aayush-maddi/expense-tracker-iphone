import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, Uuid, event, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """Append-only record of administrative and sensitive actions.

    No foreign keys on purpose: deleting/changing users never alters history,
    and the actor's email is copied at the time of the action. Rows are never
    updated or deleted by the app (ORM guard below); in PostgreSQL a trigger
    (see the admin migration) rejects UPDATE/DELETE outright.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_actor", "actor_user_id", "created_at"),
        Index("ix_audit_logs_target", "target_user_id", "created_at"),
        Index("ix_audit_logs_action", "action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_email: Mapped[str | None] = mapped_column(String(255))
    actor_role: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. USER_BLOCKED
    resource_type: Mapped[str | None] = mapped_column(String(40))  # user, transaction, session, ip, report...
    resource_id: Mapped[str | None] = mapped_column(String(64))
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    target_email: Mapped[str | None] = mapped_column(String(255))
    result: Mapped[str] = mapped_column(String(20), nullable=False, default="success")  # success | failure
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    details: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


@event.listens_for(AuditLog, "before_update")
def _block_update(mapper, connection, target):
    raise PermissionError("Audit logs are append-only and cannot be modified.")


@event.listens_for(AuditLog, "before_delete")
def _block_delete(mapper, connection, target):
    raise PermissionError("Audit logs are append-only and cannot be deleted.")
