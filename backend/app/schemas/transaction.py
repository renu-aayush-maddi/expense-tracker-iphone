import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import CATEGORIES, DEFAULT_CATEGORY
from app.schemas.common import OptionalStr


def normalize_category(value: str | None) -> str | None:
    """Accept any capitalisation ("food" -> "Food"); reject unknown categories."""
    if value is None:
        return value
    for category in CATEGORIES:
        if category.lower() == value.strip().lower():
            return category
    raise ValueError(f"Category must be one of: {', '.join(CATEGORIES)}")


def validate_last4(value: str | None) -> str | None:
    if value is None:
        return value
    if len(value) != 4 or not value.isdigit():
        raise ValueError("account_last4 must be exactly 4 digits")
    return value


class TransactionCreate(BaseModel):
    # Money: positive, at most 2 decimals, fits NUMERIC(12, 2).
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    merchant_name: str = Field(min_length=1, max_length=255)
    category: str = DEFAULT_CATEGORY
    transaction_date: date
    transaction_time: time | None = None
    payment_method: OptionalStr = Field(default=None, max_length=50)
    bank: OptionalStr = Field(default=None, max_length=100)
    phonepe_transaction_id: OptionalStr = Field(default=None, max_length=64)
    upi_reference: OptionalStr = Field(default=None, max_length=64)
    utr: OptionalStr = Field(default=None, max_length=64)
    account_last4: OptionalStr = None
    notes: OptionalStr = Field(default=None, max_length=2000)
    # True/False = your choice; leave empty (null) to let the reimbursement rule decide.
    is_reimbursable: bool | None = None

    @field_validator("merchant_name")
    @classmethod
    def check_merchant(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Merchant is required")
        return value

    @field_validator("category")
    @classmethod
    def check_category(cls, value: str) -> str:
        return normalize_category(value)

    @field_validator("account_last4")
    @classmethod
    def check_last4(cls, value: str | None) -> str | None:
        return validate_last4(value)


class TransactionUpdate(BaseModel):
    """Every field is optional: only the fields you send are changed."""

    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    merchant_name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = None
    transaction_date: date | None = None
    transaction_time: time | None = None
    payment_method: OptionalStr = Field(default=None, max_length=50)
    bank: OptionalStr = Field(default=None, max_length=100)
    phonepe_transaction_id: OptionalStr = Field(default=None, max_length=64)
    upi_reference: OptionalStr = Field(default=None, max_length=64)
    utr: OptionalStr = Field(default=None, max_length=64)
    account_last4: OptionalStr = None
    notes: OptionalStr = Field(default=None, max_length=2000)
    # True/False = your choice; null = back to automatic (rule decides).
    is_reimbursable: bool | None = None

    @field_validator("merchant_name")
    @classmethod
    def check_merchant(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Merchant is required")
        return value.strip() if value else value

    @field_validator("category")
    @classmethod
    def check_category(cls, value: str | None) -> str | None:
        return normalize_category(value)

    @field_validator("account_last4")
    @classmethod
    def check_last4(cls, value: str | None) -> str | None:
        return validate_last4(value)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: Decimal  # serialised as a string, e.g. "183.00", to keep it exact
    merchant_name: str
    category: str
    transaction_date: date
    transaction_time: time | None
    payment_method: str | None
    bank: str | None
    phonepe_transaction_id: str | None
    upi_reference: str | None
    utr: str | None
    account_last4: str | None
    source: str
    is_reimbursable: bool
    reimbursable_set_by: str | None
    extraction_method: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class TransactionDetailOut(TransactionOut):
    """The single-transaction view also includes the raw OCR text (for debugging)."""

    raw_ocr_text: str | None


class TransactionListResponse(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int
    pages: int


class FilterOptions(BaseModel):
    categories: list[str]
    banks: list[str]
    payment_methods: list[str]
    sources: list[str]
