from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.client_ip import get_client_ip
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.services import session_service

# Used to spend the same time on unknown emails as on wrong passwords,
# so attackers can't discover which emails are registered.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class EmailAlreadyRegistered(Exception):
    pass


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


def register_user(db: Session, email: str, password: str, full_name: str | None, request=None) -> User:
    if get_user_by_email(db, email):
        raise EmailAlreadyRegistered()
    user = User(
        email=email.lower(),
        hashed_password=hash_password(password),
        full_name=full_name,
        registration_ip=get_client_ip(request) if request is not None else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def check_password(db: Session, email: str, password: str) -> tuple[User | None, bool]:
    """Returns (user or None, password_ok). Constant-ish time for unknown emails."""
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None, False
    return user, verify_password(password, user.hashed_password)


def start_session(db: Session, user: User, request) -> str:
    """Create a server-side session and return its access token."""
    session = session_service.create_session(db, user, request)
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = get_client_ip(request)
    user.last_activity_at = user.last_login_at
    db.commit()
    return create_access_token(str(user.id), str(session.id), expires_delta=session_service.session_lifetime(user))


def set_password(user: User, new_password: str) -> None:
    user.hashed_password = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
