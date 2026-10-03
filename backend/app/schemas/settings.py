import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiTokenCreate(BaseModel):
    name: str = Field(default="iPhone Shortcut", min_length=1, max_length=100)


class ApiTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    token_hint: str
    created_at: datetime
    last_used_at: datetime | None


class ApiTokenCreated(ApiTokenOut):
    # The plain token. Returned ONCE, at creation time only.
    token: str


class BankAccountCreate(BaseModel):
    account_last4: str
    bank_name: str = Field(min_length=1, max_length=100)

    @field_validator("account_last4")
    @classmethod
    def check_last4(cls, value: str) -> str:
        value = value.strip()
        if len(value) != 4 or not value.isdigit():
            raise ValueError("account_last4 must be exactly 4 digits")
        return value

    @field_validator("bank_name")
    @classmethod
    def strip_bank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Bank name is required")
        return value


class BankAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_last4: str
    bank_name: str
    created_at: datetime


class ReimbursementRule(BaseModel):
    enabled: bool = True
    # Words to look for in the merchant name (whole words, any capitalisation).
    keywords: list[str] = Field(min_length=1, max_length=30)
    # 0 = Monday … 6 = Sunday
    weekdays: list[int] = Field(max_length=7)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values:
            word = " ".join(value.split()).lower()
            if not word:
                continue
            if len(word) < 2 or len(word) > 50:
                raise ValueError("Each keyword must be 2–50 characters")
            if word not in cleaned:
                cleaned.append(word)
        if not cleaned:
            raise ValueError("Add at least one keyword")
        return cleaned

    @field_validator("weekdays")
    @classmethod
    def check_weekdays(cls, values: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in values):
            raise ValueError("Weekdays must be between 0 (Monday) and 6 (Sunday)")
        return sorted(set(values))
