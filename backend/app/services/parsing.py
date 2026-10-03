"""Generic types shared by every receipt/statement parser.

A parser (PhonePe today; Gmail, CSV, bank PDFs later) turns raw text into a
ParseResult, then `validate_result` decides whether it can be trusted. The
importer doesn't care which parser produced it.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any

MAX_AMOUNT = Decimal("1000000")  # ₹10 lakh – anything bigger is almost certainly an OCR error
EARLIEST_YEAR = 2016  # UPI/PhonePe launched in 2016

# How the fields were extracted (stored on the transaction for transparency).
METHOD_RULES = "rules"  # regex parser only
METHOD_AI = "ai"  # regex parser + LLM filled in missing fields
METHOD_REVIEWED = "reviewed"  # confirmed by the user on the review screen


@dataclass
class ParsedTransaction:
    merchant_name: str | None = None
    amount: Decimal | None = None
    transaction_date: date | None = None
    transaction_time: time | None = None
    phonepe_transaction_id: str | None = None
    utr: str | None = None
    upi_reference: str | None = None
    account_last4: str | None = None
    bank: str | None = None
    payment_method: str | None = None
    message: str | None = None
    upi_id: str | None = None  # the payee's UPI handle, e.g. bigbasket@payuaxis
    category: str | None = None
    direction: str = "debit"  # "debit" (money out) or "credit" (money in)
    extraction_method: str = METHOD_RULES


@dataclass
class ParseResult:
    data: ParsedTransaction
    # Problems that make the result untrustworthy -> manual review required.
    issues: list[str] = field(default_factory=list)
    # Things worth knowing that don't block saving.
    warnings: list[str] = field(default_factory=list)
    # Distinct amounts seen when the parser couldn't decide between them.
    amount_candidates: list[Decimal] = field(default_factory=list)
    # True when the only doubt is whether a leading "2" is really a misread ₹
    # (e.g. "21,420.25" = ₹1,420.25 or ₹21,420.25?). Only the user can settle that.
    rupee_ambiguous: bool = False
    empty_text: bool = False

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)

    @property
    def is_empty(self) -> bool:
        """Nothing useful was recognised at all (wrong image, blank OCR...)."""
        d = self.data
        return not any([d.amount, d.merchant_name, d.phonepe_transaction_id, d.utr, d.upi_reference])

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe version (dates/decimals as strings) for API responses and storage."""
        result = {}
        for key, value in asdict(self.data).items():
            if isinstance(value, time):
                value = value.isoformat(timespec="minutes")
            elif isinstance(value, date):
                value = value.isoformat()
            elif isinstance(value, Decimal):
                value = str(value)
            result[key] = value
        result["warnings"] = list(self.warnings)
        result["amount_candidates"] = [str(a) for a in self.amount_candidates]
        return result


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


def validate_result(result: ParseResult, today: date, require_identifier: bool = True) -> ParseResult:
    """(Re)compute `result.issues` from the extracted data.

    Kept separate from parsing so it can run again after the LLM fallback has
    filled in missing fields.
    """
    d = result.data
    issues: list[str] = []

    if result.empty_text:
        issues.append("The receipt text is empty.")

    if d.amount is None:
        if result.rupee_ambiguous and len(result.amount_candidates) == 2:
            low, high = sorted(result.amount_candidates)
            issues.append(
                f"The ₹ sign may have been read as a '2'. Is the amount {format_inr(low)} or {format_inr(high)}? "
                "Pick the right one."
            )
        elif len(result.amount_candidates) > 1:
            listed = ", ".join(str(a) for a in sorted(result.amount_candidates))
            issues.append(f"Several different amounts were found: {listed}.")
        else:
            issues.append("Amount could not be found.")
    elif d.amount <= 0:
        issues.append("Amount must be greater than zero.")
    elif d.amount > MAX_AMOUNT:
        issues.append(f"Amount {d.amount} is unusually large; please confirm it.")

    if not d.merchant_name:
        issues.append("Merchant could not be found.")

    if d.transaction_date is None:
        issues.append("Transaction date could not be found.")
    elif d.transaction_date > today + timedelta(days=1):
        issues.append(f"Transaction date {d.transaction_date.isoformat()} is in the future.")
    elif d.transaction_date.year < EARLIEST_YEAR:
        issues.append(f"Transaction date {d.transaction_date.isoformat()} looks wrong.")

    if d.direction == "credit":
        issues.append("This receipt is for money received, not an expense.")

    if require_identifier and not d.phonepe_transaction_id and not d.utr:
        issues.append("No PhonePe transaction ID or UTR found, so duplicates can't be detected reliably.")

    result.issues = issues
    return result
