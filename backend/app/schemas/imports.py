import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.transaction import TransactionOut

# OCR text from a single receipt is a few hundred characters. 20k is a generous cap.
MAX_OCR_TEXT_LENGTH = 20_000

ImportStatus = Literal["created", "duplicate", "review_required", "invalid"]


class PhonePeImportRequest(BaseModel):
    ocr_text: str = Field(min_length=1, max_length=MAX_OCR_TEXT_LENGTH)


class ImportResponse(BaseModel):
    success: bool
    status: ImportStatus
    # Human-friendly one-liner. The iPhone Shortcut simply displays this.
    message: str
    # How the receipt was read: "ocr" (server OCR), "openai_fallback" (vision fallback) or "text" (legacy upload)
    extraction_source: str | None = None
    transaction: TransactionOut | None = None
    existing_transaction_id: uuid.UUID | None = None
    review_id: uuid.UUID | None = None
    parsed_data: dict[str, Any] | None = None
    issues: list[str] = []


class PendingImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    parsed_data: dict[str, Any]
    issues: list[str]
    created_at: datetime


class PendingImportDetailOut(PendingImportOut):
    raw_text: str
    has_image: bool = False
