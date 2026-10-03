"""Generic import pipeline, independent of where the text came from.

    raw text -> parser -> enrich (bank, category) -> duplicate check
             -> validate -> save transaction  OR  store for manual review

To support a new source (Gmail, CSV, bank PDF, another payment app), write a
parser that returns a ParseResult and register it in PARSERS.
"""

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import SOURCE_PHONEPE
from app.models import BankAccount, PendingImport, Transaction
from app.services import categorizer, duplicate_detector, transaction_service
from app.services.parsing import ParseResult
from app.services.phonepe_parser import parse_phonepe_receipt, useful_message
from app.services.transaction_service import DuplicateTransactionError

# source name -> parser function(text, today) -> ParseResult
PARSERS: dict[str, Callable[[str, date], ParseResult]] = {
    SOURCE_PHONEPE: parse_phonepe_receipt,
}


class SimilarTransactionError(Exception):
    """A transaction with the same date, amount and merchant already exists."""

    def __init__(self, existing: Transaction):
        self.existing = existing
        super().__init__("A similar transaction already exists")


@dataclass
class ImportOutcome:
    status: str  # "created" | "duplicate" | "review_required" | "invalid"
    message: str
    parse_result: ParseResult | None = None
    transaction: Transaction | None = None
    existing: Transaction | None = None
    pending: PendingImport | None = None


def format_inr(amount: Decimal) -> str:
    """183 -> '₹183', 12450.5 -> '₹12,450.50', 125000 -> '₹1,25,000' (Indian grouping)."""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    rupees, paise = divmod(amount, 1)
    digits = str(int(rupees))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"₹{digits}" + (f".{int(paise * 100):02d}" if paise else "")


def _lookup_bank(db: Session, user_id: uuid.UUID, account_last4: str | None) -> str | None:
    if not account_last4:
        return None
    return db.scalar(
        select(BankAccount.bank_name).where(BankAccount.user_id == user_id, BankAccount.account_last4 == account_last4)
    )


def suggest_category(db: Session, user_id: uuid.UUID, merchant_name: str | None) -> str:
    """Prefer the category the user chose last time for this merchant; else use the rules."""
    if merchant_name:
        previous = transaction_service.get_last_category_for_merchant(db, user_id, merchant_name)
        if previous:
            return previous
    return categorizer.categorize(merchant_name)


def _transaction_fields(result: ParseResult) -> dict:
    d = result.data
    return {
        "amount": d.amount,
        "merchant_name": d.merchant_name,
        "category": d.category,
        "transaction_date": d.transaction_date,
        "transaction_time": d.transaction_time,
        "payment_method": d.payment_method,
        "bank": d.bank,
        "phonepe_transaction_id": d.phonepe_transaction_id,
        "upi_reference": d.upi_reference,
        "utr": d.utr,
        "account_last4": d.account_last4,
        "notes": useful_message(d.message),
    }


def _text_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.strip().encode("utf-8")).hexdigest()


def _store_pending(db: Session, user_id: uuid.UUID, source: str, raw_text: str, result: ParseResult) -> PendingImport:
    """Save an uncertain import for review. Re-sharing the same receipt reuses the same review."""
    text_hash = _text_hash(raw_text)
    pending = db.scalar(
        select(PendingImport).where(PendingImport.user_id == user_id, PendingImport.raw_text_hash == text_hash)
    )
    if pending is None:
        pending = PendingImport(user_id=user_id, source=source, raw_text=raw_text, raw_text_hash=text_hash)
        db.add(pending)
    pending.parsed_data = result.to_dict()
    pending.issues = list(result.issues)
    try:
        db.commit()
    except IntegrityError:  # two identical requests at the same moment
        db.rollback()
        pending = db.scalar(
            select(PendingImport).where(PendingImport.user_id == user_id, PendingImport.raw_text_hash == text_hash)
        )
    return pending


def import_text(db: Session, user_id: uuid.UUID, source: str, raw_text: str, today: date) -> ImportOutcome:
    parser = PARSERS[source]
    result = parser(raw_text, today)
    data = result.data

    if result.is_empty:
        return ImportOutcome(
            status="invalid",
            message="Couldn't read a receipt from this image. Make sure you shared a completed PhonePe receipt.",
            parse_result=result,
        )

    # Enrich: bank from the user's account mapping, and a suggested category.
    data.bank = _lookup_bank(db, user_id, data.account_last4) or data.bank
    data.category = suggest_category(db, user_id, data.merchant_name)

    # 1) Strong duplicate check – even uncertain parses can be recognised as duplicates by ID.
    existing = duplicate_detector.find_by_identifiers(
        db, user_id, phonepe_transaction_id=data.phonepe_transaction_id, utr=data.utr, upi_reference=data.upi_reference
    )
    if existing:
        return ImportOutcome(status="duplicate", message="Transaction already exists", parse_result=result, existing=existing)

    # 2) Uncertain? Never guess – store it for review.
    if result.needs_review:
        pending = _store_pending(db, user_id, source, raw_text, result)
        return ImportOutcome(
            status="review_required",
            message="Transaction requires review. Open the Expense Tracker to confirm it.",
            parse_result=result,
            pending=pending,
        )

    fields = _transaction_fields(result)

    # 3) Fallback duplicate check: same date + amount + merchant (+ account / time).
    existing = duplicate_detector.find_by_fallback(
        db,
        user_id,
        transaction_date=data.transaction_date,
        amount=data.amount,
        merchant_name=data.merchant_name,
        account_last4=data.account_last4,
        transaction_time=data.transaction_time,
    )
    if existing:
        return ImportOutcome(status="duplicate", message="Transaction already exists", parse_result=result, existing=existing)

    # 4) Save. The unique constraints catch a duplicate arriving at the same instant.
    try:
        transaction = transaction_service.create_transaction(db, user_id, fields, source=source, raw_ocr_text=raw_text)
    except DuplicateTransactionError as error:
        return ImportOutcome(
            status="duplicate", message="Transaction already exists", parse_result=result, existing=error.existing
        )

    return ImportOutcome(
        status="created",
        message=f"Expense added: {format_inr(transaction.amount)} — {transaction.merchant_name}",
        parse_result=result,
        transaction=transaction,
    )


def confirm_pending(
    db: Session, pending: PendingImport, fields: dict, allow_similar: bool = False
) -> Transaction:
    """Turn a reviewed pending import into a real transaction."""
    if not allow_similar:
        similar = duplicate_detector.find_by_fallback(
            db,
            pending.user_id,
            transaction_date=fields["transaction_date"],
            amount=fields["amount"],
            merchant_name=fields["merchant_name"],
            account_last4=fields.get("account_last4"),
            transaction_time=fields.get("transaction_time"),
        )
        if similar:
            raise SimilarTransactionError(similar)

    # Deleting the pending row and creating the transaction happen in one commit.
    db.delete(pending)
    return transaction_service.create_transaction(
        db, pending.user_id, fields, source=pending.source, raw_ocr_text=pending.raw_text
    )
