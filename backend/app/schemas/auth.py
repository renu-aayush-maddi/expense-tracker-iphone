import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.core.permissions import permissions_for
from app.core.security import BCRYPT_MAX_BYTES
from app.schemas.common import OptionalStr


def check_password_rules(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes")
    if value.strip() != value:
        raise ValueError("Password must not start or end with spaces")
    return value


class RegisterRequest(BaseModel):
    # Only these fields are accepted: a client can't register itself as an admin.
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8)
    full_name: OptionalStr = Field(default=None, max_length=120)

    @field_validator("password")
    @classmethod
    def password_rules(cls, value: str) -> str:
        return check_password_rules(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_rules(cls, value: str) -> str:
        return check_password_rules(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    must_change_password: bool
    created_at: datetime

    @computed_field
    @property
    def permissions(self) -> list[str]:
        """What this user may do in the admin area (the server enforces it; the UI only reads it)."""
        return sorted(permissions_for(self.role))


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
