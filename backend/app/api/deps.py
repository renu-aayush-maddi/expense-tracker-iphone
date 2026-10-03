"""Reusable FastAPI dependencies: database session and the current user."""

import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import IMPORT_TOKEN_PREFIX, decode_access_token, hash_import_token
from app.db.session import get_db
from app.models import ApiToken, User

bearer_scheme = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated. Please log in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _user_from_jwt(token: str, db: Session) -> User:
    user_id = decode_access_token(token)
    if not user_id:
        raise UNAUTHORIZED
    try:
        user = db.get(User, uuid.UUID(user_id))
    except ValueError:
        raise UNAUTHORIZED
    if user is None:
        raise UNAUTHORIZED
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Normal web-app authentication: `Authorization: Bearer <JWT>`."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UNAUTHORIZED
    if credentials.credentials.startswith(IMPORT_TOKEN_PREFIX):
        # Import tokens are deliberately limited to the import endpoint.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Import tokens can only be used for importing transactions.",
        )
    return _user_from_jwt(credentials.credentials, db)


def get_import_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Import endpoints accept either a JWT (web app) or a personal import token (iPhone Shortcut)."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UNAUTHORIZED

    token = credentials.credentials
    if not token.startswith(IMPORT_TOKEN_PREFIX):
        return _user_from_jwt(token, db)

    api_token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_import_token(token)))
    if api_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid import token. Create a new one in Settings.",
        )
    user = db.get(User, api_token.user_id)
    if user is None:
        raise UNAUTHORIZED
    api_token.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return user
