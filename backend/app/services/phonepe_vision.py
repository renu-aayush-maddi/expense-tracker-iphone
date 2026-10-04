"""OpenAI Vision fallback: read the ORIGINAL receipt image when server OCR is
missing or unsure about something.

* Only called when OCR + the existing parser couldn't produce a trustworthy result.
* The model must answer in a strict JSON schema (structured outputs); free text
  is never used as data.
* Every value is validated here (formats) and again by the normal
  `validate_result` rules. The backend stays the source of truth.
* The request is sent with store=False. The image and the response are never logged.
"""

import base64
import logging
import re
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.parsing import METHOD_OPENAI_FALLBACK, ParsedTransaction, ParseResult, validate_result

logger = logging.getLogger("app.vision")

INSTRUCTIONS = """You extract payment details from a screenshot of a PhonePe (Indian UPI) transaction receipt.
Read the values exactly as printed. Never guess or invent a value; use null when a value isn't visible.

- is_phonepe_receipt: true only if the image is a payment receipt/transaction detail screen.
- direction: "paid" if money was paid/sent, "received" if money came in, else "unknown".
- merchant_name: who was paid ("Paid to"), as printed, without the UPI handle (e.g. name@bank).
- amount: the amount paid in rupees as digits, e.g. "183" or "1,250.50". The ₹ symbol is not part of the value.
- transaction_date: YYYY-MM-DD. transaction_time: HH:MM in 24-hour time.
- phonepe_transaction_id: the "Transaction ID", starts with T followed by digits.
- utr: the UTR / UPI reference number (digits).
- account_last4: last 4 digits of the masked account in "Debited from" (e.g. XXXXXX096929 -> 6929)."""


class VisionReceipt(BaseModel):
    is_phonepe_receipt: bool
    direction: Literal["paid", "received", "unknown"]
    merchant_name: str | None = Field(description="Who was paid, as printed")
    amount: str | None = Field(description="Amount paid, digits only, e.g. '183' or '1,250.50'")
    transaction_date: str | None = Field(description="YYYY-MM-DD")
    transaction_time: str | None = Field(description="HH:MM, 24-hour")
    phonepe_transaction_id: str | None = Field(description="T followed by digits")
    utr: str | None = Field(description="UTR / UPI reference number")
    account_last4: str | None = Field(description="Last 4 digits of the debited account")


@dataclass
class VisionOutcome:
    status: str  # "ok" | "disabled" | "error"
    receipt: VisionReceipt | None = None
    error: str | None = None


def is_enabled() -> bool:
    return bool(settings.OPENAI_API_KEY) and settings.VISION_FALLBACK_ENABLED


def _call_openai(jpeg: bytes) -> VisionReceipt | None:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.VISION_TIMEOUT_SECONDS, max_retries=1)
    options = {}
    if settings.OPENAI_VISION_MODEL.startswith(("gpt-5", "o")):
        options["reasoning"] = {"effort": "low"}
    image_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    response = client.responses.parse(
        model=settings.OPENAI_VISION_MODEL,
        instructions=INSTRUCTIONS,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Extract the payment details from this receipt."},
                {"type": "input_image", "image_url": image_url, "detail": "high"},
            ],
        }],
        text_format=VisionReceipt,
        store=False,  # don't keep the receipt on OpenAI's side
        **options,
    )
    return response.output_parsed


def extract_from_image(jpeg: bytes) -> VisionOutcome:
    """Never raises: returns status "disabled"/"error" instead."""
    if not is_enabled():
        return VisionOutcome(status="disabled")
    logger.info("OpenAI vision fallback triggered (model %s)", settings.OPENAI_VISION_MODEL)
    try:
        receipt = _call_openai(jpeg)
    except Exception as error:  # network, auth, quota, refusal, timeout...
        logger.warning("OpenAI vision fallback failed: %s", type(error).__name__)
        return VisionOutcome(status="error", error=type(error).__name__)
    if receipt is None:
        logger.warning("OpenAI vision fallback returned no structured output")
        return VisionOutcome(status="error", error="NoStructuredOutput")
    logger.info("OpenAI vision fallback succeeded")
    return VisionOutcome(status="ok", receipt=receipt)


# ---------------------------------------------------------------- validation of model output
def clean_amount(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = re.sub(r"[^\d.,]", "", value).replace(",", "")
    if not re.fullmatch(r"\d{1,9}(\.\d{1,2})?", cleaned):
        return None
    try:
        amount = Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def clean_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value.strip()) if value else None
    except ValueError:
        return None


def clean_time(value: str | None) -> time | None:
    if not value:
        return None
    match = re.fullmatch(r"\s*([01]?\d|2[0-3]):([0-5]\d)(:[0-5]\d)?\s*", value)
    return time(int(match.group(1)), int(match.group(2))) if match else None


def clean_transaction_id(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"\s+", "", value).upper()
    return compact if re.fullmatch(r"T\d{15,30}", compact) else None


def clean_utr(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[\s\-]", "", value).upper()
    if re.fullmatch(r"\d{10,22}", compact):
        return compact
    if re.fullmatch(r"[A-Z0-9]{12,22}", compact) and sum(c.isdigit() for c in compact) >= 8 and "XXX" not in compact:
        return compact
    return None


def clean_last4(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits[-4:] if len(digits) >= 4 else None


def clean_merchant(value: str | None) -> str | None:
    if not value:
        return None
    from app.services.phonepe_parser import _split_upi_handle  # reuse the parser's own rule

    name, _handle = _split_upi_handle(" ".join(value.split()))
    name = re.sub(r"(\.{2,}|…)\s*$", "", name).strip(" -:,.'\"")
    return name[:255] or None


def to_parse_result(receipt: VisionReceipt, today: date) -> ParseResult:
    """Convert (and format-check) the model's answer into the parser's result type."""
    data = ParsedTransaction(
        merchant_name=clean_merchant(receipt.merchant_name),
        amount=clean_amount(receipt.amount),
        transaction_date=clean_date(receipt.transaction_date),
        transaction_time=clean_time(receipt.transaction_time),
        phonepe_transaction_id=clean_transaction_id(receipt.phonepe_transaction_id),
        utr=clean_utr(receipt.utr),
        account_last4=clean_last4(receipt.account_last4),
        payment_method="UPI",
        direction="credit" if receipt.direction == "received" else "debit",
        extraction_method=METHOD_OPENAI_FALLBACK,
    )
    result = ParseResult(data=data)
    for field_name, raw in (("amount", receipt.amount), ("transaction ID", receipt.phonepe_transaction_id),
                            ("UTR", receipt.utr), ("date", receipt.transaction_date)):
        cleaned = {"amount": data.amount, "transaction ID": data.phonepe_transaction_id,
                   "UTR": data.utr, "date": data.transaction_date}[field_name]
        if raw and cleaned is None:
            result.warnings.append(f"AI returned an invalid {field_name}; it was ignored.")
    return validate_result(result, today)
