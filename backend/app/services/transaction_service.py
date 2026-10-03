from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as dt_date
from decimal import Decimal

from sqlalchemy import extract, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import CATEGORIES, PAYMENT_METHODS, SOURCE_MANUAL, SOURCES
from app.models import Transaction
from app.services import duplicate_detector


class DuplicateTransactionError(Exception):
    def __init__(self, existing: Transaction | None = None):
        self.existing = existing
        super().__init__("Transaction already exists")


@dataclass
class TransactionFilters:
    date: dt_date | None = None
    date_from: dt_date | None = None
    date_to: dt_date | None = None
    month: int | None = None
    year: int | None = None
    category: str | None = None
    bank: str | None = None
    payment_method: str | None = None
    merchant: str | None = None
    search: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    source: str | None = None


SORT_FIELDS = {
    "date": (Transaction.transaction_date, Transaction.transaction_time, Transaction.created_at),
    "amount": (Transaction.amount,),
    "merchant": (Transaction.merchant_name,),
    "category": (Transaction.category,),
    "created": (Transaction.created_at,),
}


def _apply_filters(query, filters: TransactionFilters):
    f = filters
    if f.date:
        query = query.where(Transaction.transaction_date == f.date)
    if f.date_from:
        query = query.where(Transaction.transaction_date >= f.date_from)
    if f.date_to:
        query = query.where(Transaction.transaction_date <= f.date_to)
    if f.year:
        query = query.where(extract("year", Transaction.transaction_date) == f.year)
    if f.month:
        query = query.where(extract("month", Transaction.transaction_date) == f.month)
    if f.category:
        query = query.where(Transaction.category == f.category)
    if f.bank:
        query = query.where(func.lower(Transaction.bank) == f.bank.lower())
    if f.payment_method:
        query = query.where(func.lower(Transaction.payment_method) == f.payment_method.lower())
    if f.source:
        query = query.where(Transaction.source == f.source)
    if f.merchant:
        query = query.where(Transaction.merchant_name.ilike(f"%{f.merchant}%"))
    if f.min_amount is not None:
        query = query.where(Transaction.amount >= f.min_amount)
    if f.max_amount is not None:
        query = query.where(Transaction.amount <= f.max_amount)
    if f.search:
        term = f"%{f.search}%"
        query = query.where(
            or_(
                Transaction.merchant_name.ilike(term),
                Transaction.notes.ilike(term),
                Transaction.bank.ilike(term),
                Transaction.category.ilike(term),
                Transaction.utr.ilike(term),
                Transaction.phonepe_transaction_id.ilike(term),
            )
        )
    return query


def list_transactions(
    db: Session,
    user_id: uuid.UUID,
    filters: TransactionFilters,
    sort_by: str = "date",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Transaction], int]:
    base = _apply_filters(select(Transaction).where(Transaction.user_id == user_id), filters)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    columns = SORT_FIELDS.get(sort_by, SORT_FIELDS["date"])
    order = [c.desc().nulls_last() if sort_order == "desc" else c.asc().nulls_last() for c in columns]
    order.append(Transaction.id)  # stable order for pagination

    items = db.scalars(base.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    return list(items), total


def get_transaction(db: Session, user_id: uuid.UUID, transaction_id: uuid.UUID) -> Transaction | None:
    return db.scalar(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user_id)
    )


def _save(db: Session, transaction: Transaction) -> Transaction:
    """Commit, turning a unique-constraint violation into DuplicateTransactionError."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateTransactionError()
    db.refresh(transaction)
    return transaction


def create_transaction(
    db: Session,
    user_id: uuid.UUID,
    data: dict,
    source: str = SOURCE_MANUAL,
    raw_ocr_text: str | None = None,
) -> Transaction:
    existing = duplicate_detector.find_by_identifiers(
        db,
        user_id,
        phonepe_transaction_id=data.get("phonepe_transaction_id"),
        utr=data.get("utr"),
        upi_reference=data.get("upi_reference"),
    )
    if existing:
        raise DuplicateTransactionError(existing)

    transaction = Transaction(user_id=user_id, source=source, raw_ocr_text=raw_ocr_text, **data)
    db.add(transaction)
    return _save(db, transaction)


def update_transaction(db: Session, transaction: Transaction, changes: dict) -> Transaction:
    existing = duplicate_detector.find_by_identifiers(
        db,
        transaction.user_id,
        phonepe_transaction_id=changes.get("phonepe_transaction_id"),
        utr=changes.get("utr"),
        upi_reference=changes.get("upi_reference"),
        exclude_id=transaction.id,
    )
    if existing:
        raise DuplicateTransactionError(existing)

    for field, value in changes.items():
        setattr(transaction, field, value)
    return _save(db, transaction)


def delete_transaction(db: Session, transaction: Transaction) -> None:
    db.delete(transaction)
    db.commit()


def get_filter_options(db: Session, user_id: uuid.UUID) -> dict:
    """Values for the filter dropdowns: defaults merged with what the user actually used."""

    def distinct(column) -> list[str]:
        rows = db.scalars(
            select(column).where(Transaction.user_id == user_id, column.is_not(None)).distinct()
        ).all()
        return [r for r in rows if r]

    used_methods = distinct(Transaction.payment_method)
    return {
        "categories": CATEGORIES,
        "banks": sorted(distinct(Transaction.bank), key=str.lower),
        "payment_methods": PAYMENT_METHODS + sorted(m for m in used_methods if m not in PAYMENT_METHODS),
        "sources": SOURCES,
    }


def get_last_category_for_merchant(db: Session, user_id: uuid.UUID, merchant_name: str) -> str | None:
    """If the user already categorised this merchant before, reuse their choice."""
    return db.scalar(
        select(Transaction.category)
        .where(
            Transaction.user_id == user_id,
            func.lower(Transaction.merchant_name) == merchant_name.strip().lower(),
        )
        .order_by(Transaction.updated_at.desc())
        .limit(1)
    )
