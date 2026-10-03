from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models import User

# Used to spend the same time on unknown emails as on wrong passwords,
# so attackers can't discover which emails are registered.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class EmailAlreadyRegistered(Exception):
    pass


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


def register_user(db: Session, email: str, password: str, full_name: str | None) -> User:
    if get_user_by_email(db, email):
        raise EmailAlreadyRegistered()
    user = User(email=email.lower(), hashed_password=hash_password(password), full_name=full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
