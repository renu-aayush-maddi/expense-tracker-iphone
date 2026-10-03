"""Duplicate detection, shared by every import source.

1. Strong check: PhonePe transaction ID / UTR / UPI reference. These are unique
   per payment, so a match means "definitely the same transaction". The database
   also enforces this with unique constraints.
2. Fallback check (only when no identifiers exist): same date + amount +
   merchant (+ account last 4 and time when known).
"""

import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Transaction


def find_by_identifiers(
    db: Session,
    user_id: uuid.UUID,
    phonepe_transaction_id: str | None = None,
    utr: str | None = None,
    upi_reference: str | None = None,
    exclude_id: uuid.UUID | None = None,
) -> Transaction | None:
    conditions = []
    if phonepe_transaction_id:
        conditions.append(Transaction.phonepe_transaction_id == phonepe_transaction_id)
    # UTR and UPI reference are often the same number, so compare them crosswise.
    for reference in {utr, upi_reference} - {None, ""}:
        conditions.append(Transaction.utr == reference)
        conditions.append(Transaction.upi_reference == reference)
    if not conditions:
        return None

    query = select(Transaction).where(Transaction.user_id == user_id, or_(*conditions))
    if exclude_id is not None:
        query = query.where(Transaction.id != exclude_id)
    return db.scalars(query.limit(1)).first()


def find_by_fallback(
    db: Session,
    user_id: uuid.UUID,
    transaction_date: date,
    amount: Decimal,
    merchant_name: str,
    account_last4: str | None = None,
    transaction_time: time | None = None,
) -> Transaction | None:
    query = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.transaction_date == transaction_date,
        Transaction.amount == amount,
        func.lower(Transaction.merchant_name) == merchant_name.strip().lower(),
    )
    if account_last4:
        query = query.where(or_(Transaction.account_last4 == account_last4, Transaction.account_last4.is_(None)))
    if transaction_time:
        query = query.where(or_(Transaction.transaction_time == transaction_time, Transaction.transaction_time.is_(None)))
    return db.scalars(query.limit(1)).first()


def find_duplicate(db: Session, user_id: uuid.UUID, data: dict) -> Transaction | None:
    """Run the strong check first, then the fallback check."""
    existing = find_by_identifiers(
        db,
        user_id,
        phonepe_transaction_id=data.get("phonepe_transaction_id"),
        utr=data.get("utr"),
        upi_reference=data.get("upi_reference"),
    )
    if existing:
        return existing

    if data.get("transaction_date") and data.get("amount") and data.get("merchant_name"):
        return find_by_fallback(
            db,
            user_id,
            transaction_date=data["transaction_date"],
            amount=data["amount"],
            merchant_name=data["merchant_name"],
            account_last4=data.get("account_last4"),
            transaction_time=data.get("transaction_time"),
        )
    return None
