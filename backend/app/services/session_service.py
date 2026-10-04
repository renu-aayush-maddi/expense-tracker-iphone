"""Server-side sessions behind the Bearer tokens."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.client_ip import get_client_ip, get_user_agent
from app.core.config import settings
from app.core.permissions import is_admin
from app.models import User, UserSession

TOUCH_INTERVAL = timedelta(seconds=60)  # don't write last_seen on every single request


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """SQLite (tests) returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def session_lifetime(user: User) -> timedelta:
    if is_admin(user.role):
        return timedelta(hours=settings.ADMIN_SESSION_HOURS)
    return timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def create_session(db: Session, user: User, request) -> UserSession:
    """A fresh session for every login (prevents session fixation)."""
    now = _now()
    session = UserSession(
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + session_lifetime(user),
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    db.add(session)
    db.flush()
    return session


def is_valid(session: UserSession | None, user: User) -> bool:
    if session is None or session.revoked_at is not None or session.user_id != user.id:
        return False
    now = _now()
    if _aware(session.expires_at) <= now:
        return False
    if is_admin(user.role) and now - _aware(session.last_seen_at) > timedelta(minutes=settings.ADMIN_IDLE_TIMEOUT_MINUTES):
        return False  # admin idle timeout
    return True


def touch(db: Session, session: UserSession, user: User) -> None:
    now = _now()
    if now - _aware(session.last_seen_at) >= TOUCH_INTERVAL:
        session.last_seen_at = now
        user.last_activity_at = now
        db.commit()


def revoke(db: Session, session: UserSession, reason: str, by: User | None = None) -> None:
    if session.revoked_at is None:
        session.revoked_at = _now()
        session.revoked_reason = reason
        session.revoked_by_id = by.id if by else None


def revoke_all(db: Session, user_id: uuid.UUID, reason: str, by: User | None = None, keep: uuid.UUID | None = None) -> int:
    query = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason, revoked_by_id=by.id if by else None)
    )
    if keep is not None:
        query = query.where(UserSession.id != keep)
    return db.execute(query).rowcount or 0


def active_sessions_filter():
    return (UserSession.revoked_at.is_(None)) & (UserSession.expires_at > _now())


def active_count(db: Session, user_id: uuid.UUID) -> int:
    return len(db.scalars(select(UserSession.id).where(UserSession.user_id == user_id, active_sessions_filter())).all())
