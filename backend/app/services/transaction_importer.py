"""Generic import pipeline, independent of where the text came from.

    raw text -> parser -> duplicate check (IDs) -> LLM fallback (only if needed)
             -> validate -> duplicate check (fallback) -> save transaction
                                                       OR store for manual review

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
from app.services import categorizer, duplicate_detector, llm_extractor, transaction_service
from app.services.parsing import METHOD_AI, METHOD_REVIEWED, ParsedTransaction, ParseResult, validate_result
from app.services.phonepe_parser import parse_phonepe_receipt, useful_message
from app.services.transaction_service import DuplicateTransactionError

# source name -> parser function(text, today) -> ParseResult
PARSERS: dict[str, Callable[[str, date], ParseResult]] = {
    SOURCE_PHONEPE: parse_phonepe_receipt,
}

MAX_REPROCESS = 25  # pending imports re-run per request (each may call the LLM)


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


# ---------------------------------------------------------------- LLM fallback
def apply_llm_fallback(result: ParseResult, raw_text: str, today: date) -> None:
    """Fill missing amount/merchant/date/time from the LLM, after verifying each
    value against the OCR text, then re-validate. Mutates `result`."""
    d = result.data
    if d.amount is not None and d.merchant_name and d.transaction_date is not None:
        return  # nothing the LLM can help with (e.g. only the IDs are missing)
    answer = llm_extractor.extract(raw_text)
    if answer is None:
        return

    filled = []
    if d.amount is None:
        amount = llm_extractor.to_amount(answer.amount)
        # The amount must be a number that's really in the text (not an ID, date or time),
        # and one of the parser's candidates if it found several.
        allowed = set(result.amount_candidates) or llm_extractor.amount_numbers_in(raw_text)
        if amount is not None and amount in allowed:
            d.amount = amount
            filled.append("amount")
    if not d.merchant_name and answer.merchant_name and llm_extractor.merchant_in_text(answer.merchant_name, raw_text):
        d.merchant_name = answer.merchant_name.strip()[:255]
        filled.append("merchant")
    if d.transaction_date is None and llm_extractor.to_date(answer.transaction_date):
        d.transaction_date = llm_extractor.to_date(answer.transaction_date)
        filled.append("date")
    if d.transaction_time is None and llm_extractor.to_time(answer.transaction_time):
        d.transaction_time = llm_extractor.to_time(answer.transaction_time)
        filled.append("time")
    if answer.direction == "received":
        d.direction = "credit"  # be safe: money received is never auto-saved as an expense

    if filled:
        d.extraction_method = METHOD_AI
        result.warnings.append("Read with AI help: " + ", ".join(filled) + ".")
    validate_result(result, today)


# ---------------------------------------------------------------- pending reviews
def _text_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.strip().encode("utf-8")).hexdigest()


def _matching_pending(db: Session, user_id: uuid.UUID, raw_text: str, data: ParsedTransaction) -> list[PendingImport]:
    """Pending imports for the same receipt: same text, or same transaction ID / UTR
    (re-sharing a receipt often gives slightly different OCR text)."""
    text_hash = _text_hash(raw_text)
    matches = []
    for pending in db.scalars(select(PendingImport).where(PendingImport.user_id == user_id)).all():
        parsed = pending.parsed_data or {}
        if (
            pending.raw_text_hash == text_hash
            or (data.phonepe_transaction_id and parsed.get("phonepe_transaction_id") == data.phonepe_transaction_id)
            or (data.utr and parsed.get("utr") == data.utr)
        ):
            matches.append(pending)
    return matches


def _resolve_pending(db: Session, user_id: uuid.UUID, raw_text: str, data: ParsedTransaction) -> None:
    """The receipt is now saved (or known to be saved): remove its pending reviews."""
    matches = _matching_pending(db, user_id, raw_text, data)
    for pending in matches:
        db.delete(pending)
    if matches:
        db.commit()


def _store_pending(db: Session, user_id: uuid.UUID, source: str, raw_text: str, result: ParseResult) -> PendingImport:
    """Save an uncertain import for review. Re-sharing the same receipt updates the same review."""
    text_hash = _text_hash(raw_text)
    matches = _matching_pending(db, user_id, raw_text, result.data)
    pending = next((p for p in matches if p.raw_text_hash == text_hash), matches[0] if matches else None)
    if pending is None:
        pending = PendingImport(user_id=user_id, source=source)
        db.add(pending)
    pending.raw_text = raw_text
    pending.raw_text_hash = text_hash
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


# ---------------------------------------------------------------- main pipeline
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
        "extraction_method": d.extraction_method,
    }


def _duplicate(result: ParseResult, existing: Transaction | None) -> ImportOutcome:
    return ImportOutcome(status="duplicate", message="Transaction already exists", parse_result=result, existing=existing)


def import_text(db: Session, user_id: uuid.UUID, source: str, raw_text: str, today: date) -> ImportOutcome:
    result = PARSERS[source](raw_text, today)
    data = result.data

    if result.is_empty:
        return ImportOutcome(
            status="invalid",
            message="Couldn't read a receipt from this image. Make sure you shared a completed PhonePe receipt.",
            parse_result=result,
        )

    # 1) Strong duplicate check first – re-shares are recognised without calling the LLM.
    existing = duplicate_detector.find_by_identifiers(
        db, user_id, phonepe_transaction_id=data.phonepe_transaction_id, utr=data.utr, upi_reference=data.upi_reference
    )
    if existing:
        _resolve_pending(db, user_id, raw_text, data)
        return _duplicate(result, existing)

    # 2) Parser unsure? Let the LLM fill the gaps (verified against the text).
    if result.needs_review:
        apply_llm_fallback(result, raw_text, today)

    # Enrich: bank from the user's account mapping, and a suggested category.
    data.bank = _lookup_bank(db, user_id, data.account_last4) or data.bank
    data.category = suggest_category(db, user_id, data.merchant_name)

    # 3) Still uncertain? Never guess – store it for review.
    if result.needs_review:
        pending = _store_pending(db, user_id, source, raw_text, result)
        return ImportOutcome(
            status="review_required",
            message="Transaction requires review. Open the Expense Tracker to confirm it.",
            parse_result=result,
            pending=pending,
        )

    # 4) Fallback duplicate check: same date + amount + merchant (+ account / time).
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
        _resolve_pending(db, user_id, raw_text, data)
        return _duplicate(result, existing)

    # 5) Save. The unique constraints catch a duplicate arriving at the same instant.
    try:
        transaction = transaction_service.create_transaction(
            db, user_id, _transaction_fields(result), source=source, raw_ocr_text=raw_text
        )
    except DuplicateTransactionError as error:
        return _duplicate(result, error.existing)

    _resolve_pending(db, user_id, raw_text, data)
    return ImportOutcome(
        status="created",
        message=f"Expense added: {format_inr(transaction.amount)} — {transaction.merchant_name}",
        parse_result=result,
        transaction=transaction,
    )


def reprocess_pending(db: Session, user_id: uuid.UUID, today: date) -> dict[str, int]:
    """Run every pending import through the (possibly improved) pipeline again."""
    counts = {"created": 0, "duplicate": 0, "review_required": 0, "invalid": 0}
    pendings = db.scalars(
        select(PendingImport)
        .where(PendingImport.user_id == user_id)
        .order_by(PendingImport.created_at)
        .limit(MAX_REPROCESS)
    ).all()
    for pending in pendings:
        if pending not in db:  # already resolved while handling an earlier copy of the same receipt
            counts["duplicate"] += 1
            continue
        outcome = import_text(db, user_id, pending.source, pending.raw_text, today)
        counts[outcome.status] += 1
    return counts


def confirm_pending(db: Session, pending: PendingImport, fields: dict, allow_similar: bool = False) -> Transaction:
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
        db,
        pending.user_id,
        {**fields, "extraction_method": METHOD_REVIEWED},
        source=pending.source,
        raw_ocr_text=pending.raw_text,
    )
