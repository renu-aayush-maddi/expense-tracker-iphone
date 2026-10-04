"""Platform-wide numbers for the admin dashboard and reports (aggregated in SQL)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import ADMIN_ROLES
from app.core.timeutils import today_local
from app.models import AuditLog, IpBlock, SecurityEvent, Transaction, User, UserSession
from app.models.user import STATUS_BLOCKED, STATUS_DELETED
from app.services import ip_block_service, security_service, session_service
from app.services.admin_service import as_date, daily_series, money

ACTIVE_DAYS = 30  # "active user" = activity within this many days


def local_tz() -> ZoneInfo:
    return ZoneInfo(settings.APP_TIMEZONE)


def local_start(day: date) -> datetime:
    """Start of a day in APP_TIMEZONE, as an aware datetime (compared against UTC timestamps)."""
    return datetime.combine(day, time.min, tzinfo=local_tz())


def local_day(column, db: Session):
    """The calendar day of a timestamp in APP_TIMEZONE (PostgreSQL); plain date elsewhere (tests)."""
    if db.get_bind().dialect.name == "postgresql":
        return func.date(func.timezone(settings.APP_TIMEZONE, column))
    return func.date(column)


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def _daily(db: Session, model, column, start: date, end: date, *conditions, value=None, money_values=False):
    day = local_day(column, db)
    rows = db.execute(
        select(day, value if value is not None else func.count())
        .where(column >= local_start(start), column < local_start(end + timedelta(days=1)), *conditions)
        .group_by(day)
    ).all()
    return daily_series({as_date(d): v for d, v in rows}, start, end, money_values)


def dashboard(db: Session, start: date, end: date) -> dict:
    today = today_local()
    t0 = local_start(today)
    week = local_start(today - timedelta(days=6))
    month = local_start(today.replace(day=1))
    range_start, range_end = local_start(start), local_start(end + timedelta(days=1))
    active_since = local_start(today - timedelta(days=ACTIVE_DAYS))
    not_deleted = User.status != STATUS_DELETED
    visible_tx = Transaction.deleted_at.is_(None)

    total_users = _count(db, User, not_deleted)
    active_users = _count(db, User, not_deleted, User.last_activity_at >= active_since)
    tx_total, tx_value, tx_avg = db.execute(
        select(func.count(), func.sum(Transaction.amount), func.avg(Transaction.amount)).where(visible_tx)
    ).one()

    login_today = SecurityEvent.created_at >= t0
    in_range = (SecurityEvent.created_at >= range_start) & (SecurityEvent.created_at < range_end)

    # Active users per day: anyone who logged in or added a transaction that day.
    active_pairs = set()
    for model, column, user_col, extra in (
        (SecurityEvent, SecurityEvent.created_at, SecurityEvent.user_id, SecurityEvent.event_type == security_service.LOGIN_SUCCESS),
        (Transaction, Transaction.created_at, Transaction.user_id, visible_tx),
    ):
        day = local_day(column, db)
        for d, uid in db.execute(
            select(day, user_col).where(column >= range_start, column < range_end, user_col.is_not(None), extra).distinct()
        ).all():
            active_pairs.add((as_date(d), uid))
    active_by_day: dict = {}
    for d, _ in active_pairs:
        active_by_day[d] = active_by_day.get(d, 0) + 1

    recent_admin_actions = db.scalars(
        select(AuditLog).where(AuditLog.actor_role.in_([r.value for r in ADMIN_ROLES]))
        .order_by(AuditLog.created_at.desc()).limit(8)
    ).all()

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat(), "timezone": settings.APP_TIMEZONE},
        "users": {
            "total": total_users,
            "active": active_users,
            "inactive": total_users - active_users,
            "new_today": _count(db, User, User.created_at >= t0),
            "new_week": _count(db, User, User.created_at >= week),
            "new_month": _count(db, User, User.created_at >= month),
            "new_in_range": _count(db, User, User.created_at >= range_start, User.created_at < range_end),
            "blocked": _count(db, User, User.status == STATUS_BLOCKED),
            "admins": _count(db, User, User.role.in_([r.value for r in ADMIN_ROLES]), not_deleted),
        },
        "transactions": {
            "total": tx_total or 0,
            "today": _count(db, Transaction, visible_tx, Transaction.created_at >= t0),
            "week": _count(db, Transaction, visible_tx, Transaction.created_at >= week),
            "month": _count(db, Transaction, visible_tx, Transaction.created_at >= month),
            "total_value": str(money(tx_value)),
            "average_value": str(money(tx_avg)),
        },
        "security": {
            "login_attempts_today": _count(db, SecurityEvent, login_today, SecurityEvent.event_type.in_(
                [security_service.LOGIN_SUCCESS, security_service.LOGIN_FAILED, security_service.LOGIN_BLOCKED])),
            "failed_logins_today": _count(db, SecurityEvent, login_today, SecurityEvent.event_type == security_service.LOGIN_FAILED),
            "successful_logins_today": _count(db, SecurityEvent, login_today, SecurityEvent.event_type == security_service.LOGIN_SUCCESS),
            "active_sessions": _count(db, UserSession, session_service.active_sessions_filter()),
            "blocked_ips": len(db.scalars(ip_block_service.active_blocks_query()).all()),
            "blocked_users": _count(db, User, User.status == STATUS_BLOCKED),
            "suspicious_in_range": _count(db, SecurityEvent, in_range, SecurityEvent.event_type.in_(security_service.SUSPICIOUS_TYPES)),
        },
        "series": {
            "registrations": _daily(db, User, User.created_at, start, end),
            "transactions": _daily(db, Transaction, Transaction.created_at, start, end, visible_tx),
            "transaction_value": _daily(db, Transaction, Transaction.created_at, start, end, visible_tx,
                                        value=func.coalesce(func.sum(Transaction.amount), 0), money_values=True),
            "logins_success": _daily(db, SecurityEvent, SecurityEvent.created_at, start, end,
                                     SecurityEvent.event_type == security_service.LOGIN_SUCCESS),
            "logins_failed": _daily(db, SecurityEvent, SecurityEvent.created_at, start, end,
                                    SecurityEvent.event_type == security_service.LOGIN_FAILED),
            "active_users": daily_series(active_by_day, start, end),
        },
        "recent_admin_actions": [
            {"id": a.id, "at": a.created_at, "actor": a.actor_email, "action": a.action, "target": a.target_email, "result": a.result}
            for a in recent_admin_actions
        ],
    }


# ---------------------------------------------------------------- reports
def users_report(db: Session, start: date, end: date) -> dict:
    rs, re_ = local_start(start), local_start(end + timedelta(days=1))
    by_status = dict(db.execute(select(User.status, func.count()).group_by(User.status)).all())
    by_role = dict(db.execute(select(User.role, func.count()).where(User.status != STATUS_DELETED).group_by(User.role)).all())
    active = _count(db, User, User.status != STATUS_DELETED, User.last_activity_at >= rs, User.last_activity_at < re_)
    total = _count(db, User, User.status != STATUS_DELETED)
    return {
        "new_users": _count(db, User, User.created_at >= rs, User.created_at < re_),
        "active_users": active,
        "inactive_users": total - active,
        "blocked_users": by_status.get(STATUS_BLOCKED, 0),
        "by_status": by_status,
        "by_role": by_role,
        "registrations": _daily(db, User, User.created_at, start, end),
    }


def transactions_report(db: Session, start: date, end: date) -> dict:
    in_range = (Transaction.transaction_date >= start) & (Transaction.transaction_date <= end) & Transaction.deleted_at.is_(None)
    count, total, avg = db.execute(
        select(func.count(), func.sum(Transaction.amount), func.avg(Transaction.amount)).where(in_range)
    ).one()
    by_category = db.execute(
        select(Transaction.category, func.count(), func.sum(Transaction.amount))
        .where(in_range).group_by(Transaction.category).order_by(func.sum(Transaction.amount).desc())
    ).all()
    by_merchant = db.execute(
        select(Transaction.merchant_name, func.count(), func.sum(Transaction.amount))
        .where(in_range).group_by(Transaction.merchant_name).order_by(func.sum(Transaction.amount).desc()).limit(20)
    ).all()
    return {
        "transaction_count": count or 0,
        "total_spending": str(money(total)),
        "average_spending": str(money(avg)),
        "by_category": [{"label": c, "count": n, "total": str(money(t))} for c, n, t in by_category],
        "by_merchant": [{"label": m, "count": n, "total": str(money(t))} for m, n, t in by_merchant],
    }


def security_report(db: Session, start: date, end: date) -> dict:
    rs, re_ = local_start(start), local_start(end + timedelta(days=1))
    in_range = (SecurityEvent.created_at >= rs) & (SecurityEvent.created_at < re_)
    by_type = dict(db.execute(select(SecurityEvent.event_type, func.count()).where(in_range).group_by(SecurityEvent.event_type)).all())
    failing_ips = db.execute(
        select(SecurityEvent.ip_address, func.count())
        .where(in_range, SecurityEvent.event_type == security_service.LOGIN_FAILED)
        .group_by(SecurityEvent.ip_address).order_by(func.count().desc()).limit(10)
    ).all()
    return {
        "login_attempts": sum(by_type.get(t, 0) for t in (security_service.LOGIN_SUCCESS, security_service.LOGIN_FAILED, security_service.LOGIN_BLOCKED)),
        "successful_logins": by_type.get(security_service.LOGIN_SUCCESS, 0),
        "failed_logins": by_type.get(security_service.LOGIN_FAILED, 0),
        "blocked_logins": by_type.get(security_service.LOGIN_BLOCKED, 0),
        "blocked_ip_requests": by_type.get(security_service.BLOCKED_IP_REQUEST, 0),
        "ips_blocked_in_range": _count(db, IpBlock, IpBlock.created_at >= rs, IpBlock.created_at < re_),
        "active_ip_blocks": len(db.scalars(ip_block_service.active_blocks_query()).all()),
        "suspicious_events": {t: by_type[t] for t in security_service.SUSPICIOUS_TYPES if t in by_type},
        "top_failing_ips": [{"ip_address": ip, "failed_logins": n} for ip, n in failing_ips],
        "logins_failed": _daily(db, SecurityEvent, SecurityEvent.created_at, start, end,
                                SecurityEvent.event_type == security_service.LOGIN_FAILED),
    }


