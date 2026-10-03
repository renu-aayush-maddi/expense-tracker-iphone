"""LLM fallback for receipts the rule-based parser can't fully read.

Used only when the parser is missing the amount, merchant or date. The LLM's
answer is never trusted blindly:

* It receives a REDACTED copy of the OCR text (transaction IDs, UTRs and
  account numbers removed) – those are always extracted by the rule-based
  parser, never by the LLM.
* The amount it returns must literally appear as a number in the OCR text.
* The merchant it returns must appear in the OCR text.
* The result then goes through the same validation as any other parse; if
  anything is still uncertain the import goes to manual review.

If OPENAI_API_KEY is not set, or the call fails/times out, the import simply
falls back to manual review.
"""

import logging
import re
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = """You read OCR text from Indian UPI payment receipts (mostly PhonePe screenshots).
Extract the payment details.

Important facts about this OCR:
- The rupee symbol ₹ is often misread as ¥, Y, Z, F, %, ?, *, 2 or dropped entirely.
- Identifiers have been replaced with [TXN_ID], [REF_NUMBER] and [ACCOUNT]. Never use them.
- Dates and times are never the amount.

Rules:
- amount: the money that was paid, written exactly as its digits appear in the text
  (keep commas/decimals, no currency symbol). If the amount appears several times, it is the same payment.
  If you can't tell which number is the paid amount, return null.
- merchant_name: who was paid, as written in the text (business or person name, without the UPI handle).
- transaction_date: YYYY-MM-DD. transaction_time: HH:MM in 24-hour format.
- direction: "paid" if money was sent/paid, "received" if money came in, otherwise "unknown".
- Use null for anything you can't find. Never invent values."""


class LLMReceipt(BaseModel):
    amount: str | None = Field(description="Paid amount exactly as its digits appear, e.g. '183' or '1,250.50'")
    merchant_name: str | None
    transaction_date: str | None = Field(description="YYYY-MM-DD")
    transaction_time: str | None = Field(description="HH:MM, 24-hour")
    direction: Literal["paid", "received", "unknown"]


def is_enabled() -> bool:
    return bool(settings.OPENAI_API_KEY) and settings.LLM_FALLBACK_ENABLED


def redact(text: str) -> str:
    """Remove identifiers before sending text to a third party."""
    text = re.sub(r"\bT\s*\d[\d\s]{14,}", "[TXN_ID]", text)
    text = re.sub(r"[Xx×*•·]{2,}[\s\-]*\d{3,}", "[ACCOUNT]", text)
    text = re.sub(r"\d(?:[\s\-]?\d){9,}", "[REF_NUMBER]", text)  # UTRs, phone numbers, long refs
    return text


def numbers_in(text: str) -> set[Decimal]:
    """Every number written in the text (commas removed), e.g. {183, 1250.50}."""
    found = set()
    for token in re.findall(r"\d[\d,]*(?:\.\d{1,2})?", text):
        try:
            found.add(Decimal(token.replace(",", "")))
        except InvalidOperation:
            continue
    return found


def amount_numbers_in(raw_text: str) -> set[Decimal]:
    """Numbers that could be the amount: everything in the redacted text except
    dates and times (so the LLM can't pass off "3" from "3 October" as ₹3)."""
    text = redact(raw_text)
    text = re.sub(r"\b\d{1,2}\s*[:.]\s*\d{2}(\s*[:.]\s*\d{2})?\s*([AaPp]\.?\s*[Mm]\.?)?", " ", text)  # times
    text = re.sub(r"\b\d{1,2}(st|nd|rd|th)?\s*[-\s]\s*[A-Za-z]{3,9}\.?,?\s*[-\s]\s*\d{4}\b", " ", text)  # 3 Oct 2026
    text = re.sub(r"\b[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}\b", " ", text)  # Oct 3, 2026
    text = re.sub(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b", " ", text)  # 03/10/2026
    return numbers_in(text)


def to_amount(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = re.sub(r"[^\d.,]", "", value).replace(",", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return amount.quantize(Decimal("0.01")) if amount > 0 else None


def to_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def to_time(value: str | None) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None


def merchant_in_text(merchant: str, text: str) -> bool:
    """Every word of the merchant name must appear in the OCR text."""
    words = re.findall(r"[a-z0-9]+", merchant.lower())
    haystack = text.lower()
    return bool(words) and all(word in haystack for word in words)


def _call_openai(redacted_text: str) -> LLMReceipt | None:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS, max_retries=1)
    options = {}
    if settings.OPENAI_MODEL.startswith(("gpt-5", "o")):
        options["reasoning"] = {"effort": "low"}  # reasoning models only; keeps it fast
    response = client.responses.parse(
        model=settings.OPENAI_MODEL,
        instructions=INSTRUCTIONS,
        input=redacted_text,
        text_format=LLMReceipt,
        store=False,  # don't keep receipts on OpenAI's side
        **options,
    )
    return response.output_parsed


def extract(ocr_text: str) -> LLMReceipt | None:
    """Ask the LLM to read the receipt. Returns None if disabled or on any error."""
    if not is_enabled():
        return None
    try:
        return _call_openai(redact(ocr_text))
    except Exception as error:  # network, timeout, auth, quota... -> manual review instead
        # Log the error type only – never the receipt text.
        logger.warning("LLM fallback failed: %s", type(error).__name__)
        return None
