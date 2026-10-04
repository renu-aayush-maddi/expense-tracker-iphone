"""Queries and actions behind the admin API (kept out of the routers)."""

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import extract, func, or_, select
from sqlalchemy.orm import Session

from app.core.client_ip import describe_user_agent
from app.core.permissions import Role
from app.core.timeutils import today_local
from app.models import AuditLog, SecurityEvent, Transaction, User, UserSession
from app.models.user import STATUS_ACTIVE, STATUS_DELETED
from app.schemas.admin import mask
from app.services import audit_service, security_service, session_service


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- user list / detail
def _transaction_totals():
    return (
        select(
            Transaction.user_id.label("user_id"),
            func.count().label("count"),
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
        )
        .where(Transaction.deleted_at.is_(None))
        .group_by(Transaction.user_id)
        .subquery()
    )


def _active_session_counts():
    return (
        select(UserSession.user_id.label("user_id"), func.count().label("active"))
        .where(session_service.active_sessions_filter())
        .group_by(UserSession.user_id)
        .subquery()
    )


USER_SORTS = {
    "created": User.created_at,
    "email": User.email,
    "last_login": User.last_login_at,
    "last_activity": User.last_activity_at,
    "role": User.role,
    "status": User.status,
}


def users_query(
    q: str | None = None,
    role: str | None = None,
    status_filter: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    active_from: datetime | None = None,
    active_to: datetime | None = None,
    sort_by: str = "created",
    sort_order: str = "desc",
    admins_only: bool = False,
):
    tx = _transaction_totals()
    sessions = _active_session_counts()
    query = (
        select(
            User,
            func.coalesce(tx.c.count, 0),
            func.coalesce(tx.c.total, 0),
            func.coalesce(sessions.c.active, 0),
        )
        .outerjoin(tx, tx.c.user_id == User.id)
        .outerjoin(sessions, sessions.c.user_id == User.id)
    )
    if q:
        term = f"%{q.strip()}%"
        query = query.where(or_(User.email.ilike(term), User.full_name.ilike(term)))
    if role:
        query = query.where(User.role == role)
    if admins_only:
        query = query.where(User.role != Role.USER)
    if status_filter:
        query = query.where(User.status == status_filter)
    else:
        query = query.where(User.status != STATUS_DELETED)  # deleted accounts only when asked for
    if created_from:
        query = query.where(User.created_at >= created_from)
    if created_to:
        query = query.where(User.created_at < created_to)
    if active_from:
        query = query.where(User.last_activity_at >= active_from)
    if active_to:
        query = query.where(User.last_activity_at < active_to)

    if sort_by == "transactions":
        column = func.coalesce(tx.c.count, 0)
    elif sort_by == "total":
        column = func.coalesce(tx.c.total, 0)
    else:
        column = USER_SORTS.get(sort_by, User.created_at)
    ordered = column.desc().nulls_last() if sort_order == "desc" else column.asc().nulls_last()
    return query.order_by(ordered, User.id)


def user_row(user: User, count, total, active) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "status": user.status,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "last_activity_at": user.last_activity_at,
        "last_login_ip": user.last_login_ip,
        "registration_ip": user.registration_ip,
        "transaction_count": int(count or 0),
        "transaction_total": Decimal(total or 0).quantize(Decimal("0.01")),
        "active_sessions": int(active or 0),
    }


def user_detail(db: Session, user: User) -> dict:
    row = db.execute(users_query(status_filter=user.status).where(User.id == user.id)).first()
    data = user_row(*row)
    failed = security_service.failed_logins_since_last_success(db, user)
    data.update(
        updated_at=user.updated_at,
        status_reason=user.status_reason,
        status_changed_at=user.status_changed_at,
        status_changed_by_email=user.status_changed_by_email,
        must_change_password=user.must_change_password,
        password_changed_at=user.password_changed_at,
        failed_logins_recent=failed,
        locked=failed >= security_service.settings.LOCKOUT_THRESHOLD,
    )
    return data


# ---------------------------------------------------------------- user actions
def ensure_other_super_admin(db: Session, target: User) -> None:
    if target.role != Role.SUPER_ADMIN:
        return
    others = db.scalar(
        select(func.count()).select_from(User).where(
            User.role == Role.SUPER_ADMIN, User.status == STATUS_ACTIVE, User.id != target.id
        )
    )
    if not others:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There must always be at least one active super admin.")


def change_status(db: Session, request, admin: User, target: User, new_status: str, reason: str | None, action: str) -> User:
    if target.status == STATUS_DELETED and new_status != STATUS_DELETED and action not in ("USER_RESTORED",):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This account is deleted. Restore it first.")
    if new_status != STATUS_ACTIVE:
        ensure_other_super_admin(db, target)
    old_status = target.status
    target.status = new_status
    target.status_reason = reason
    target.status_changed_at = now()
    target.status_changed_by_id = admin.id
    target.status_changed_by_email = admin.email
    if new_status == STATUS_DELETED:
        target.deleted_at = now()
    elif old_status == STATUS_DELETED:
        target.deleted_at = None
    revoked = 0
    if new_status != STATUS_ACTIVE:  # blocked/disabled/suspended/deleted: kick out every device now
        revoked = session_service.revoke_all(db, target.id, reason=f"account_{new_status}", by=admin)
        if revoked:
            security_service.record_event(db, security_service.SESSION_REVOKED, request=request, user=target,
                                          reason=f"{revoked} session(s) revoked: account {new_status}", commit=False)
    audit_service.record(
        db, action, actor=admin, request=request, resource_type="user", resource_id=target.id, target=target,
        details={"from": old_status, "to": new_status, "reason": reason, "sessions_revoked": revoked}, commit=False,
    )
    db.commit()
    return target


# ---------------------------------------------------------------- user activity / security / finance
def activity_timeline(db: Session, user: User, limit: int = 100) -> list[dict]:
    """One chronological list from security events, admin actions on the user, and transactions."""
    items: list[dict] = []
    for e in db.scalars(
        select(SecurityEvent).where(SecurityEvent.user_id == user.id).order_by(SecurityEvent.created_at.desc()).limit(limit)
    ):
        items.append({"at": e.created_at, "kind": "security", "type": e.event_type, "success": e.success,
                      "ip": e.ip_address, "detail": e.reason, "severity": e.severity})
    for a in db.scalars(
        select(AuditLog).where(AuditLog.target_user_id == user.id).order_by(AuditLog.created_at.desc()).limit(limit)
    ):
        items.append({"at": a.created_at, "kind": "admin", "type": a.action, "success": a.result == "success",
                      "ip": a.ip_address, "detail": f"by {a.actor_email or 'system'}", "severity": "info"})
    for t in db.scalars(
        select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.created_at.desc()).limit(limit)
    ):
        label = "Imported PhonePe transaction" if t.source == "phonepe" else "Added transaction"
        items.append({"at": t.created_at, "kind": "transaction", "type": t.source, "success": True, "ip": None,
                      "detail": f"{label} ({t.category})" + (" – deleted by admin" if t.deleted_at else ""),
                      "severity": "info", "transaction_id": str(t.id)})

    def sort_key(item):
        at = item["at"]
        return at if at.tzinfo else at.replace(tzinfo=timezone.utc)

    return sorted(items, key=sort_key, reverse=True)[:limit]


def user_security(db: Session, user: User) -> dict:
    ip_rows = db.execute(
        select(
            SecurityEvent.ip_address,
            func.min(SecurityEvent.created_at),
            func.max(SecurityEvent.created_at),
            func.count(),
        )
        .where(SecurityEvent.user_id == user.id, SecurityEvent.ip_address.is_not(None))
        .group_by(SecurityEvent.ip_address)
        .order_by(func.max(SecurityEvent.created_at).desc())
        .limit(50)
    ).all()
    sessions = db.scalars(
        select(UserSession).where(UserSession.user_id == user.id).order_by(UserSession.created_at.desc()).limit(25)
    ).all()
    events = db.scalars(
        select(SecurityEvent).where(SecurityEvent.user_id == user.id).order_by(SecurityEvent.created_at.desc()).limit(50)
    ).all()
    return {
        "known_ips": [
            {"ip_address": ip, "first_seen": first, "last_seen": last, "events": count} for ip, first, last, count in ip_rows
        ],
        "sessions": [session_out(s, user) for s in sessions],
        "events": events,
    }


def session_status(session: UserSession, user: User) -> str:
    if session.revoked_at is not None:
        return "revoked"
    return "active" if session_service.is_valid(session, user) else "expired"


def session_out(session: UserSession, user: User) -> dict:
    return {
        "id": session.id,
        "user_id": session.user_id,
        "user_email": user.email,
        "created_at": session.created_at,
        "last_seen_at": session.last_seen_at,
        "expires_at": session.expires_at,
        "ip_address": session.ip_address,
        "user_agent": session.user_agent,
        "device": describe_user_agent(session.user_agent),
        "status": session_status(session, user),
        "revoked_reason": session.revoked_reason,
    }


def user_finance(db: Session, user: User) -> dict:
    visible = (Transaction.user_id == user.id) & Transaction.deleted_at.is_(None)
    count, total, average, highest = db.execute(
        select(func.count(), func.sum(Transaction.amount), func.avg(Transaction.amount), func.max(Transaction.amount)).where(visible)
    ).one()
    recent = db.scalars(
        select(Transaction).where(visible).order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(10)
    ).all()
    today = today_local()
    start_year, start_month = (today.year * 12 + today.month - 1 - 11) // 12, (today.year * 12 + today.month - 1 - 11) % 12 + 1
    year_col, month_col = extract("year", Transaction.transaction_date), extract("month", Transaction.transaction_date)
    rows = dict(
        ((int(y), int(m)), v)
        for y, m, v in db.execute(
            select(year_col, month_col, func.sum(Transaction.amount))
            .where(visible, Transaction.transaction_date >= date(start_year, start_month, 1))
            .group_by(year_col, month_col)
        ).all()
    )
    monthly = []
    for offset in range(12):
        index = start_year * 12 + start_month - 1 + offset
        y, m = index // 12, index % 12 + 1
        monthly.append({"label": f"{calendar.month_abbr[m]} {y}", "total": str(money(rows.get((y, m))))})
    return {
        "transaction_count": count or 0,
        # Money as exact strings ("250.00"), like the rest of the API.
        "total_spending": str(money(total)),
        "average_transaction": str(money(average)),
        "highest_transaction": str(money(highest)),
        "recent_transactions": [
            {
                "id": t.id,
                "merchant_name": t.merchant_name,
                "amount": str(money(t.amount)),
                "category": t.category,
                "transaction_date": t.transaction_date,
                "source": t.source,
                "utr_masked": mask(t.utr),
            }
            for t in recent
        ],
        "monthly": monthly,
    }


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


# ---------------------------------------------------------------- date ranges
def resolve_range(range_key: str, start: date | None, end: date | None, today: date) -> tuple[date, date]:
    """Inclusive date range for dashboard/report filters."""
    if range_key == "custom":
        if not start or not end or start > end:
            raise HTTPException(status_code=422, detail="Choose a valid start and end date.")
        if (end - start).days > 366 * 3:
            raise HTTPException(status_code=422, detail="Date range can be at most 3 years.")
        return start, end
    days = {"today": 0, "7d": 6, "30d": 29, "90d": 89}.get(range_key, 29)
    return today - timedelta(days=days), today


def daily_series(rows: dict, start: date, end: date, money_values: bool = False) -> list[dict]:
    series = []
    day = start
    while day <= end:
        value = rows.get(day, 0)
        series.append({"date": day.isoformat(), "value": str(money(value)) if money_values else int(value or 0)})
        day += timedelta(days=1)
    return series


def as_date(value) -> date:
    """func.date() returns a date on Postgres but a string on SQLite."""
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
