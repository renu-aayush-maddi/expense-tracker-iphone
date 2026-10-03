"""Password hashing, JWT creation/validation and personal import tokens."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# bcrypt only looks at the first 72 bytes of a password; we reject longer ones
# at the schema level so nothing is silently ignored.
BCRYPT_MAX_BYTES = 72

# Prefix lets us tell import tokens apart from JWTs in the Authorization header.
IMPORT_TOKEN_PREFIX = "etk_"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the user id inside a valid token, or None if invalid/expired."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    return payload.get("sub")


def generate_import_token() -> str:
    """Long-lived random token for the iPhone Shortcut (JWTs expire, Shortcuts can't log in)."""
    return IMPORT_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_import_token(token: str) -> str:
    """Import tokens are stored as SHA-256 hashes. They are high-entropy random
    strings, so a fast hash is appropriate (unlike passwords)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
