"""Generic types shared by every receipt/statement parser.

A parser (PhonePe today; Gmail, CSV, bank PDFs later) turns raw text into a
ParseResult. The importer doesn't care which parser produced it.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, time
from decimal import Decimal
from typing import Any


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
    category: str | None = None
    direction: str = "debit"  # "debit" (money out) or "credit" (money in)


@dataclass
class ParseResult:
    data: ParsedTransaction
    # Problems that make the result untrustworthy -> manual review required.
    issues: list[str] = field(default_factory=list)
    # Things worth knowing that don't block saving.
    warnings: list[str] = field(default_factory=list)

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
            if isinstance(value, (date, time)):
                value = value.isoformat(timespec="minutes") if isinstance(value, time) else value.isoformat()
            elif isinstance(value, Decimal):
                value = str(value)
            result[key] = value
        result["warnings"] = list(self.warnings)
        return result
