"""Generic import pipeline, independent of where the text came from.

    raw text -> parser -> duplicate check (IDs) -> LLM fallback (only if needed)
             -> validate -> duplicate check (fallback) -> save transaction
                                                       OR store for manual review

To support a new source (Gmail, CSV, bank PDF, another payment app), write a
parser that returns a ParseResult and register it in PARSERS.
"""

import hashlib
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import SOURCE_PHONEPE
from app.models import BankAccount, PendingImport, Transaction
from app.core.config import settings
from app.services import (
    categorizer,
    duplicate_detector,
    llm_extractor,
    phonepe_ocr,
    phonepe_vision,
    transaction_service,
)
from app.services.receipt_image import ReceiptImage
from app.services.parsing import (
    METHOD_AI,
    METHOD_OCR,
    METHOD_OPENAI_FALLBACK,
    METHOD_REVIEWED,
    ParsedTransaction,
    ParseResult,
    format_inr,
    validate_result,
)
from app.services.phonepe_parser import parse_phonepe_receipt, useful_message
from app.services.transaction_service import DuplicateTransactionError

# source name -> parser function(text, today) -> ParseResult
PARSERS: dict[str, Callable[[str, date], ParseResult]] = {
    SOURCE_PHONEPE: parse_phonepe_receipt,
}

logger = logging.getLogger("app.import")

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
    extraction_source: str | None = None  # "ocr" | "openai_fallback" | "text" (legacy OCR-text upload)


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
    amount_fillable = d.amount is None and not result.rupee_ambiguous
    if not amount_fillable and d.merchant_name and d.transaction_date is not None:
        return  # nothing the LLM can help with (e.g. only the IDs, or the ₹-vs-2 question, remain)
    answer = llm_extractor.extract(raw_text)
    if answer is None:
        return

    filled = []
    # "Is the leading 2 a misread ₹?" can't be answered from text – not by the LLM either.
    if d.amount is None and not result.rupee_ambiguous:
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


def _matching_pending(db: Session, user_id: uuid.UUID, content_hash: str, data: ParsedTransaction) -> list[PendingImport]:
    """Pending imports for the same receipt: same text/image, or same transaction ID / UTR
    (re-sharing a receipt often gives slightly different OCR text)."""
    matches = []
    for pending in db.scalars(select(PendingImport).where(PendingImport.user_id == user_id)).all():
        parsed = pending.parsed_data or {}
        if (
            pending.raw_text_hash == content_hash
            or (data.phonepe_transaction_id and parsed.get("phonepe_transaction_id") == data.phonepe_transaction_id)
            or (data.utr and parsed.get("utr") == data.utr)
        ):
            matches.append(pending)
    return matches


def _resolve_pending(db: Session, user_id: uuid.UUID, content_hash: str, data: ParsedTransaction) -> None:
    """The receipt is now saved (or known to be saved): remove its pending reviews."""
    matches = _matching_pending(db, user_id, content_hash, data)
    for pending in matches:
        db.delete(pending)
    if matches:
        db.commit()


def _store_pending(
    db: Session,
    user_id: uuid.UUID,
    source: str,
    raw_text: str,
    result: ParseResult,
    content_hash: str | None = None,
    image_jpeg: bytes | None = None,
    extra: dict | None = None,
) -> PendingImport:
    """Save an uncertain import for review. Re-sharing the same receipt updates the same review."""
    content_hash = content_hash or _text_hash(raw_text)
    matches = _matching_pending(db, user_id, content_hash, result.data)
    pending = next((p for p in matches if p.raw_text_hash == content_hash), matches[0] if matches else None)
    if pending is None:
        pending = PendingImport(user_id=user_id, source=source)
        db.add(pending)
    pending.raw_text = raw_text
    pending.raw_text_hash = content_hash
    pending.parsed_data = {**result.to_dict(), **(extra or {})}
    pending.issues = list(result.issues)
    if image_jpeg is not None:
        pending.image_data = image_jpeg
        pending.image_content_type = "image/jpeg"
    try:
        db.commit()
    except IntegrityError:  # two identical requests at the same moment
        db.rollback()
        pending = db.scalar(
            select(PendingImport).where(PendingImport.user_id == user_id, PendingImport.raw_text_hash == content_hash)
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
        _resolve_pending(db, user_id, _text_hash(raw_text), data)
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
        _resolve_pending(db, user_id, _text_hash(raw_text), data)
        return _duplicate(result, existing)

    # 5) Save. The unique constraints catch a duplicate arriving at the same instant.
    try:
        transaction = transaction_service.create_transaction(
            db, user_id, _transaction_fields(result), source=source, raw_ocr_text=raw_text
        )
    except DuplicateTransactionError as error:
        return _duplicate(result, error.existing)

    _resolve_pending(db, user_id, _text_hash(raw_text), data)
    return ImportOutcome(
        status="created",
        message=f"Expense added: {format_inr(transaction.amount)} — {transaction.merchant_name}",
        parse_result=result,
        transaction=transaction,
    )


# ---------------------------------------------------------------- image imports (server OCR + vision fallback)
def _mask(value: str | None) -> str:
    return f"…{value[-4:]}" if value else "-"


def ocr_is_confident(result: ParseResult, ocr: phonepe_ocr.OcrResult) -> bool:
    """OCR alone is trusted only if the existing parser + validation found every
    critical field AND the OCR engine itself was confident. Text alone isn't enough."""
    return (
        ocr.ok
        and not result.needs_review  # amount, merchant, date valid; transaction ID or UTR present; not money received
        and not result.rupee_ambiguous
        and ocr.mean_confidence >= settings.OCR_MIN_CONFIDENCE
        and ocr.min_digit_line_confidence >= 0.6
    )


def _merchant_matches(a: str, b: str) -> bool:
    """'BLINK COMMERCE PRIVA' vs 'Blink Commerce Private Limited' -> same merchant."""
    def norm(text):
        return " ".join(re.findall(r"[a-z0-9]+", text.lower()))

    x, y = norm(a), norm(b)
    if not x or not y:
        return True
    if x.startswith(y[:12]) or y.startswith(x[:12]):
        return True
    tx, ty = set(x.split()), set(y.split())
    return len(tx & ty) / max(1, min(len(tx), len(ty))) >= 0.5


def compare_ocr_and_vision(ocr: ParseResult, vision: ParseResult) -> list[str]:
    """Critical fields both sources read but read DIFFERENTLY. Any conflict -> review."""
    o, v = ocr.data, vision.data
    conflicts = []
    if v.amount is not None:
        if o.amount is not None and o.amount != v.amount:
            conflicts.append(f"amount: OCR {o.amount} vs AI {v.amount}")
        elif o.amount is None and ocr.amount_candidates and v.amount not in ocr.amount_candidates:
            listed = ", ".join(str(a) for a in ocr.amount_candidates)
            conflicts.append(f"amount: OCR saw {listed} but AI read {v.amount}")
    for label, field in (("date", "transaction_date"), ("transaction ID", "phonepe_transaction_id"),
                         ("UTR", "utr"), ("account", "account_last4")):
        a, b = getattr(o, field), getattr(v, field)
        if a and b and a != b:
            conflicts.append(f"{label}: OCR {a} vs AI {b}")
    if o.merchant_name and v.merchant_name and not _merchant_matches(o.merchant_name, v.merchant_name):
        conflicts.append(f"merchant: OCR '{o.merchant_name}' vs AI '{v.merchant_name}'")
    return conflicts


def _merge(primary: ParseResult, secondary: ParseResult) -> ParseResult:
    """Fill gaps in `primary` with values from `secondary` (never overwrite)."""
    for field in ("merchant_name", "amount", "transaction_date", "transaction_time", "phonepe_transaction_id",
                  "utr", "upi_reference", "account_last4", "bank", "message", "upi_id"):
        if getattr(primary.data, field) in (None, "") and getattr(secondary.data, field) not in (None, ""):
            setattr(primary.data, field, getattr(secondary.data, field))
    primary.warnings.extend(w for w in secondary.warnings if w not in primary.warnings)
    return primary


def _review(db, user_id, result, ocr, receipt, today, extra, message=None, source=None) -> ImportOutcome:
    # Same enrichment as saved transactions, so the review form is pre-filled sensibly.
    result.data.bank = _lookup_bank(db, user_id, result.data.account_last4) or result.data.bank
    result.data.category = suggest_category(db, user_id, result.data.merchant_name)
    pending = _store_pending(
        db, user_id, SOURCE_PHONEPE, ocr.text, result,
        content_hash=receipt.sha256, image_jpeg=receipt.jpeg_bytes(max_side=1600, quality=82), extra=extra,
    )
    logger.info("Image import needs review: %d issue(s), source=%s", len(result.issues), source)
    return ImportOutcome(
        status="review_required",
        message=message or "Transaction requires review. Open the Expense Tracker to confirm it.",
        parse_result=result,
        pending=pending,
        extraction_source=source,
    )


def import_image(db: Session, user_id: uuid.UUID, receipt: ReceiptImage, today: date) -> ImportOutcome:
    """Receipt image -> server OCR -> existing parser/validation -> (vision fallback if unsure)
    -> existing duplicate checks -> save, or the existing review queue."""
    # 1) Server OCR + the existing PhonePe parser.
    ocr = phonepe_ocr.extract_text_from_image(receipt)
    ocr_result = parse_phonepe_receipt(ocr.text, today)
    ocr_info = {"ocr": ocr.summary()}

    # 2) Re-shared receipt? Recognise it by transaction ID / UTR before spending an AI call.
    existing = duplicate_detector.find_by_identifiers(
        db, user_id, phonepe_transaction_id=ocr_result.data.phonepe_transaction_id,
        utr=ocr_result.data.utr, upi_reference=ocr_result.data.upi_reference,
    )
    if existing:
        logger.info("Image import: duplicate (txn %s)", _mask(ocr_result.data.phonepe_transaction_id))
        _resolve_pending(db, user_id, receipt.sha256, ocr_result.data)
        outcome = _duplicate(ocr_result, existing)
        outcome.extraction_source = METHOD_OCR
        return outcome

    # 3) Decide: OCR alone, or the vision fallback.
    if ocr_is_confident(ocr_result, ocr):
        final, source = ocr_result, METHOD_OCR
        final.data.extraction_method = METHOD_OCR
        logger.info("Image import: OCR result trusted (confidence %.2f)", ocr.mean_confidence)
    else:
        logger.info("Image import: OCR uncertain (%d issue(s), confidence %.2f) -> vision fallback",
                    len(ocr_result.issues), ocr.mean_confidence)
        vision = phonepe_vision.extract_from_image(receipt.jpeg_bytes())
        if vision.status != "ok":
            # No AI available/working: keep the receipt for manual review (unless it's clearly not a receipt).
            if ocr_result.is_empty and ocr.ok:
                return ImportOutcome(status="invalid", parse_result=ocr_result, extraction_source=METHOD_OCR,
                                     message="Couldn't read a receipt from this image. Make sure you shared a completed PhonePe receipt.")
            if not ocr_result.issues:
                ocr_result.issues.append("Server OCR wasn't confident enough to save this automatically.")
            ocr_result.issues.append("The AI fallback is unavailable." if vision.status == "disabled"
                                     else "The AI fallback failed.")
            return _review(db, user_id, ocr_result, ocr, receipt, today,
                           {**ocr_info, "extraction_source": METHOD_OCR, "vision": {"status": vision.status}},
                           source=METHOD_OCR)

        vision_result = phonepe_vision.to_parse_result(vision.receipt, today)
        if not vision.receipt.is_phonepe_receipt and vision_result.is_empty and ocr_result.is_empty:
            return ImportOutcome(status="invalid", parse_result=vision_result, extraction_source=METHOD_OPENAI_FALLBACK,
                                 message="This doesn't look like a PhonePe receipt.")

        conflicts = compare_ocr_and_vision(ocr_result, vision_result)
        extra = {**ocr_info, "extraction_source": METHOD_OPENAI_FALLBACK, "vision": {"status": "ok"},
                 "ocr_values": ocr_result.to_dict(), "conflicts": conflicts}
        if conflicts:
            # Never silently pick one: both readings go to review.
            merged = _merge(vision_result, ocr_result)
            merged.issues = [f"OCR and AI disagree on {c}" for c in conflicts] + merged.issues
            logger.info("Image import: OCR and vision disagree on %d field(s) -> review", len(conflicts))
            return _review(db, user_id, merged, ocr, receipt, today, extra, source=METHOD_OPENAI_FALLBACK)

        final = validate_result(_merge(vision_result, ocr_result), today)
        final.data.extraction_method = METHOD_OPENAI_FALLBACK
        source = METHOD_OPENAI_FALLBACK
        if final.needs_review:
            return _review(db, user_id, final, ocr, receipt, today, extra, source=source)

    data = final.data
    # 4) Existing enrichment: bank from the account mapping, category from history/rules (never from the AI).
    data.bank = _lookup_bank(db, user_id, data.account_last4) or data.bank
    data.category = suggest_category(db, user_id, data.merchant_name)

    # 5) Existing duplicate checks again with the final values (the AI path can't bypass them).
    existing = duplicate_detector.find_by_identifiers(
        db, user_id, phonepe_transaction_id=data.phonepe_transaction_id, utr=data.utr, upi_reference=data.upi_reference
    ) or duplicate_detector.find_by_fallback(
        db, user_id, transaction_date=data.transaction_date, amount=data.amount, merchant_name=data.merchant_name,
        account_last4=data.account_last4, transaction_time=data.transaction_time,
    )
    if existing:
        logger.info("Image import: duplicate (txn %s, utr %s)", _mask(data.phonepe_transaction_id), _mask(data.utr))
        _resolve_pending(db, user_id, receipt.sha256, data)
        outcome = _duplicate(final, existing)
        outcome.extraction_source = source
        return outcome

    # 6) Save (unique constraints still catch a simultaneous duplicate).
    try:
        transaction = transaction_service.create_transaction(
            db, user_id, _transaction_fields(final), source=SOURCE_PHONEPE, raw_ocr_text=ocr.text or None
        )
    except DuplicateTransactionError as error:
        outcome = _duplicate(final, error.existing)
        outcome.extraction_source = source
        return outcome
    _resolve_pending(db, user_id, receipt.sha256, data)
    logger.info("Image import: created via %s", source)
    return ImportOutcome(
        status="created",
        message=f"Expense added: {format_inr(transaction.amount)} — {transaction.merchant_name}",
        parse_result=final,
        transaction=transaction,
        extraction_source=source,
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
        if pending.image_data:  # image import: run OCR (+ vision) again on the stored receipt
            from app.services.receipt_image import load_receipt_image

            receipt = load_receipt_image(pending.image_data)
            receipt.sha256 = pending.raw_text_hash  # keep the original upload's identity (same review row)
            outcome = import_image(db, user_id, receipt, today)
        else:
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
