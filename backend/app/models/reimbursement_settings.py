import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReimbursementSettings(Base):
    """Per-user rule for marking transactions as company-reimbursable.

    Default: rides (Uber / Ola / Rapido) on weekdays. One row per user, created
    the first time the user changes the defaults.
    """

    __tablename__ = "reimbursement_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    keywords: Mapped[list] = mapped_column(JSON, nullable=False)  # merchant words, e.g. ["uber", "ola"]
    weekdays: Mapped[list] = mapped_column(JSON, nullable=False)  # 0 = Monday … 6 = Sunday
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
