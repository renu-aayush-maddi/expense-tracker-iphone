"""Reusable FastAPI dependencies: database session, current user, admin permissions.

Every protected request is checked on the SERVER:
  1. the token's signature and expiry,
  2. the server-side session (not revoked, not expired, admin idle timeout),
  3. the account status (only "active" accounts get in),
  4. a pending forced password change,
  5. for admin endpoints, the role's permissions.
"""

import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Permission, is_admin, permissions_for
from app.core.rate_limit import RateLimiter
from app.core.security import IMPORT_TOKEN_PREFIX, decode_access_token, hash_import_token
from app.db.session import get_db
from app.models import ApiToken, User, UserSession
from app.models.user import STATUS_ACTIVE
from app.services import security_service, session_service

bearer_scheme = HTTPBearer(auto_error=False)

# Record denied admin access at most once a minute per user+path, so a user
# hammering admin URLs can't flood the security log.
_denied_throttle = RateLimiter(max_requests=1)


def _record_denied(db: Session, request: Request, user: User, event_type: str, reason: str) -> None:
    try:
        _denied_throttle.hit(f"{event_type}:{user.id}:{request.url.path}")
    except HTTPException:
        return
    security_service.record_event(db, event_type, request=request, user=user, success=False, severity="warning", reason=reason)

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated. Please log in again.",
    headers={"WWW-Authenticate": "Bearer"},
)

STATUS_MESSAGES = {
    "blocked": "This account has been blocked. Contact the administrator.",
    "disabled": "This account has been disabled.",
    "suspended": "This account is suspended.",
    "deleted": "This account no longer exists.",
}


def inactive_account_error(user: User) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=STATUS_MESSAGES.get(user.status, "Account inactive."))


def _authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None, db: Session) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UNAUTHORIZED
    if credentials.credentials.startswith(IMPORT_TOKEN_PREFIX):
        # Import tokens are deliberately limited to the import endpoint.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Import tokens can only be used for importing transactions.",
        )
    claims = decode_access_token(credentials.credentials)
    if not claims:
        raise UNAUTHORIZED
    try:
        user = db.get(User, uuid.UUID(claims["sub"]))
        session = db.get(UserSession, uuid.UUID(claims["sid"]))
    except ValueError:
        raise UNAUTHORIZED
    if user is None or not session_service.is_valid(session, user):
        raise UNAUTHORIZED
    if user.status != STATUS_ACTIVE:
        raise inactive_account_error(user)
    session_service.touch(db, session, user)
    request.state.session = session
    request.state.user = user
    return user


def get_current_user_allow_password_change(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Authenticated user, even if they still have to change a temporary password
    (used only by /auth/me, /auth/logout and /auth/change-password)."""
    return _authenticate(request, credentials, db)


def get_current_user(user: User = Depends(get_current_user_allow_password_change)) -> User:
    """Normal web-app authentication: `Authorization: Bearer <token>`."""
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "You must change your temporary password first.", "code": "password_change_required"},
        )
    return user


def get_import_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Import endpoints accept either a login token (web app) or a personal import token (iPhone Shortcut)."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UNAUTHORIZED

    token = credentials.credentials
    if not token.startswith(IMPORT_TOKEN_PREFIX):
        return get_current_user(_authenticate(request, credentials, db))

    api_token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_import_token(token)))
    if api_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid import token. Create a new one in Settings.",
        )
    user = db.get(User, api_token.user_id)
    if user is None:
        raise UNAUTHORIZED
    if user.status != STATUS_ACTIVE:  # blocked users can't import either
        raise inactive_account_error(user)
    api_token.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return user


def require_admin(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """Any admin role. Normal users get 403 (and the attempt is recorded)."""
    if not is_admin(user.role):
        _record_denied(db, request, user, "admin_access_denied", f"{request.method} {request.url.path}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to the admin area.")
    return user


def require_permission(permission: Permission):
    """Dependency factory: `admin: User = Depends(require_permission(Permission.USERS_MANAGE))`."""

    def checker(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> User:
        if permission not in permissions_for(admin.role):
            _record_denied(db, request, admin, "admin_permission_denied",
                           f"missing {permission} for {request.method} {request.url.path}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your admin role doesn't allow this action.",
            )
        return admin

    return checker
