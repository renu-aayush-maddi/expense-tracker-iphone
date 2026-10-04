"""Helpers shared by the admin routers."""

import math
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import can_act_on
from app.core.rate_limit import RateLimiter
from app.core.security import verify_password
from app.models import User
from app.services import security_service

reauth_limiter = RateLimiter(max_requests=5)


def paginate(db: Session, query, page: int, page_size: int):
    """Count + one page of rows, in two queries (no loading the whole table)."""
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = db.execute(query.offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total, (math.ceil(total / page_size) if total else 0)


def day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def day_end(value: date) -> datetime:
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)


def get_target_user(db: Session, user_id) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def ensure_can_act(admin: User, target: User, *, allow_self: bool = False) -> None:
    """Block privilege escalation: no acting on yourself (unless allowed) and
    non-super admins may only act on plain users."""
    if target.id == admin.id and not allow_self:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can't perform this action on your own account.")
    if target.id != admin.id and not can_act_on(admin.role, target.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super admin can manage other administrators.",
        )


def confirm_password(db: Session, request: Request, admin: User, password: str) -> None:
    """Re-authentication for the most sensitive actions."""
    reauth_limiter.hit(f"reauth:{admin.id}")
    if not verify_password(password, admin.hashed_password):
        security_service.record_event(
            db, security_service.REAUTH_FAILED, request=request, user=admin, success=False, severity="warning",
            reason=f"{request.method} {request.url.path}",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password confirmation failed.")
