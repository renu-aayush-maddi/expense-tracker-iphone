import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PendingImport(Base):
    """An imported receipt that could not be parsed confidently.

    It waits here until the user reviews it in the web app, so nothing uncertain
    is ever silently saved as a real transaction.
    """

    __tablename__ = "pending_imports"
    __table_args__ = (
        # Sharing the same uncertain receipt twice must not create two reviews.
        UniqueConstraint("user_id", "raw_text_hash", name="uq_pending_imports_user_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parsed_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    issues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
