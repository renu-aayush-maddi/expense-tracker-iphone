import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import DEFAULT_CATEGORY, SOURCE_MANUAL
from app.db.base import Base


def visible_to_owner(user_id):
    """Condition for the transactions a user sees: theirs and not soft-deleted by an admin."""
    return (Transaction.user_id == user_id) & Transaction.deleted_at.is_(None)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        # Database-level duplicate protection: the same PhonePe transaction ID or
        # UTR can never be stored twice for the same user (NULLs are allowed).
        UniqueConstraint("user_id", "phonepe_transaction_id", name="uq_transactions_user_phonepe_txn_id"),
        UniqueConstraint("user_id", "utr", name="uq_transactions_user_utr"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        Index("ix_transactions_user_date", "user_id", "transaction_date"),
        Index("ix_transactions_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Money is NUMERIC(12, 2) – never float.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    merchant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Stored as plain text (not a DB enum) so it can be changed freely by the user
    # and new categories can be added without a migration.
    category: Mapped[str] = mapped_column(String(50), nullable=False, default=DEFAULT_CATEGORY)

    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_time: Mapped[time | None] = mapped_column(Time)

    payment_method: Mapped[str | None] = mapped_column(String(50))
    bank: Mapped[str | None] = mapped_column(String(100))

    phonepe_transaction_id: Mapped[str | None] = mapped_column(String(64))
    upi_reference: Mapped[str | None] = mapped_column(String(64))
    utr: Mapped[str | None] = mapped_column(String(64))
    account_last4: Mapped[str | None] = mapped_column(String(4))

    raw_ocr_text: Mapped[str | None] = mapped_column(Text)
    # How an imported transaction was read: "rules", "ai" (LLM helped) or "reviewed" (confirmed by you).
    extraction_method: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(30), nullable=False, default=SOURCE_MANUAL)
    # Company will pay this back (e.g. weekday office rides).
    is_reimbursable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Who decided: "rule" (automatic, re-evaluated when the rule changes) or "user" (never overwritten).
    reimbursable_set_by: Mapped[str | None] = mapped_column(String(10))
    notes: Mapped[str | None] = mapped_column(Text)

    # Soft delete (used by admins): the row stays for the audit trail but is hidden everywhere.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    deleted_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
