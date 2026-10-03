import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BankAccount(Base):
    """Maps the last 4 digits of an account to a bank name.

    PhonePe receipts only show "Debited from XXXXXX096929", not the bank name.
    With a mapping (6929 -> Kotak) imports fill in the bank automatically.
    """

    __tablename__ = "bank_accounts"
    __table_args__ = (UniqueConstraint("user_id", "account_last4", name="uq_bank_accounts_user_last4"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
