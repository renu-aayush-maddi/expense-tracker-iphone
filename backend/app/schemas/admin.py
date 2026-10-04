"""Request/response models for /api/admin.

Request models use extra="forbid" so unexpected fields (e.g. "role" in a
profile update) are rejected instead of silently applied (no mass assignment).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.permissions import Role
from app.schemas.common import OptionalStr

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


def mask(value: str | None, keep: int = 4) -> str | None:
    """'706226593892' -> '••••3892'. Admins see enough to match, not the full reference."""
    if not value:
        return value
    return "••••" + value[-keep:]


# ---------------------------------------------------------------- users
class AdminUserRow(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    status: str
    created_at: datetime
    last_login_at: datetime | None
    last_activity_at: datetime | None
    last_login_ip: str | None
    registration_ip: str | None
    transaction_count: int
    transaction_total: Decimal
    active_sessions: int


class AdminUserDetail(AdminUserRow):
    updated_at: datetime
    status_reason: str | None
    status_changed_at: datetime | None
    status_changed_by_email: str | None
    must_change_password: bool
    password_changed_at: datetime | None
    failed_logins_recent: int
    locked: bool


class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # role/status/password can't sneak in here

    full_name: OptionalStr = Field(default=None, max_length=120)
    email: EmailStr | None = None


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Please give a reason (at least 3 characters)")
        return value


class OptionalReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class PasswordConfirmRequest(BaseModel):
    """For the most sensitive actions the admin re-enters their own password."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500)


class RoleChangeRequest(PasswordConfirmRequest):
    role: Role


class AddAdminRequest(PasswordConfirmRequest):
    email: EmailStr
    role: Literal["read_only_admin", "admin", "super_admin"]


class TemporaryPasswordOut(BaseModel):
    temporary_password: str  # shown ONCE to the admin; the user must change it at next login
    message: str


# ---------------------------------------------------------------- transactions
class AdminTransactionRow(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    merchant_name: str
    amount: Decimal
    category: str
    transaction_date: date
    source: str
    is_reimbursable: bool
    created_at: datetime
    deleted_at: datetime | None


class AdminTransactionDetail(AdminTransactionRow):
    transaction_time: Any
    payment_method: str | None
    bank: str | None
    utr_masked: str | None
    phonepe_transaction_id_masked: str | None
    account_last4: str | None
    extraction_method: str | None
    deleted_reason: str | None
    updated_at: datetime


# ---------------------------------------------------------------- logs & security
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor_user_id: uuid.UUID | None
    actor_email: str | None
    actor_role: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    target_user_id: uuid.UUID | None
    target_email: str | None
    result: str
    ip_address: str | None
    user_agent: str | None
    details: dict


class SecurityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    event_type: str
    severity: str
    success: bool | None
    user_id: uuid.UUID | None
    email: str | None
    ip_address: str | None
    user_agent: str | None
    device: str | None = None
    reason: str | None
    details: dict


class SessionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    device: str
    status: str  # active | revoked | expired
    revoked_reason: str | None


class IpBlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ip_address: str = Field(min_length=3, max_length=45)
    reason: str = Field(min_length=3, max_length=500)
    expires_hours: int | None = Field(default=None, ge=1, le=24 * 365)


class IpBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ip_address: str
    reason: str
    blocked_by_email: str | None
    created_at: datetime
    expires_at: datetime | None
    unblocked_at: datetime | None
    unblocked_by_email: str | None


class IpSummary(BaseModel):
    ip_address: str
    first_seen: datetime
    last_seen: datetime
    users: int
    events: int
    successful_logins: int
    failed_logins: int
    blocked: bool
