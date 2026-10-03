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
