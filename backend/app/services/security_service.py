"""Security events, account lockout and basic suspicious-activity detection.

Only security-relevant facts are recorded (event type, account, IP, user agent,
result). Suspicious patterns are FLAGGED for admins – nothing is blocked
automatically except the short per-account lockout after repeated wrong passwords.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.client_ip import get_client_ip, get_user_agent
from app.core.config import settings
from app.models import SecurityEvent, User

security_logger = logging.getLogger("security")

# Event types
LOGIN_SUCCESS = "login_success"
LOGIN_FAILED = "login_failed"
LOGIN_BLOCKED = "login_blocked"  # locked account, blocked/disabled user, blocked IP
LOGOUT = "logout"
REGISTER = "register"
PASSWORD_CHANGED = "password_changed"
PASSWORD_RESET = "password_reset"  # by an admin
ACCOUNT_LOCKED = "account_locked"
SESSION_REVOKED = "session_revoked"
BLOCKED_IP_REQUEST = "blocked_ip_request"
IMPORT_REQUEST = "import_request"
REAUTH_FAILED = "reauth_failed"  # admin entered a wrong password to confirm an action
# Suspicious patterns
SUSPICIOUS_FAILED_LOGINS = "suspicious_failed_logins"
SUSPICIOUS_MANY_IPS = "suspicious_many_ips"
SUSPICIOUS_CREDENTIAL_STUFFING = "suspicious_credential_stuffing"
SUSPICIOUS_NEW_IP = "new_ip_login"
SUSPICIOUS_BLOCKED_REQUESTS = "suspicious_blocked_requests"
SUSPICIOUS_REGISTRATIONS = "suspicious_registrations"

SUSPICIOUS_TYPES = [
    ACCOUNT_LOCKED,
    SUSPICIOUS_FAILED_LOGINS,
    SUSPICIOUS_MANY_IPS,
    SUSPICIOUS_CREDENTIAL_STUFFING,
    SUSPICIOUS_NEW_IP,
    SUSPICIOUS_BLOCKED_REQUESTS,
    SUSPICIOUS_REGISTRATIONS,
]
AUTH_TYPES = [LOGIN_SUCCESS, LOGIN_FAILED, LOGIN_BLOCKED, LOGOUT, REGISTER, PASSWORD_CHANGED, PASSWORD_RESET, ACCOUNT_LOCKED]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_event(
    db: Session,
    event_type: str,
    *,
    request=None,
    user: User | None = None,
    user_id: uuid.UUID | None = None,
    email: str | None = None,
    ip: str | None = None,
    success: bool | None = None,
    reason: str | None = None,
    severity: str = "info",
    details: dict | None = None,
    commit: bool = True,
) -> SecurityEvent:
    event = SecurityEvent(
        event_type=event_type,
        severity=severity,
        success=success,
        user_id=user.id if user else user_id,
        email=(user.email if user else email) or None,
        ip_address=ip or (get_client_ip(request) if request is not None else None),
        user_agent=get_user_agent(request) if request is not None else None,
        reason=reason[:200] if reason else None,
        details=details or {},
        created_at=_now(),
    )
    db.add(event)
    if commit:
        db.commit()
    security_logger.log(
        logging.WARNING if severity != "info" else logging.INFO,
        "%s user=%s ip=%s success=%s reason=%s",
        event_type, event.user_id, event.ip_address, success, reason,
    )
    return event


def _count(db: Session, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(SecurityEvent).where(*conditions)) or 0


def _recent(minutes: int):
    return SecurityEvent.created_at >= _now() - timedelta(minutes=minutes)


# ---------------------------------------------------------------- lockout
def failed_logins_since_last_success(db: Session, user: User) -> int:
    window_start = _now() - timedelta(minutes=settings.LOCKOUT_MINUTES)
    last_success = db.scalar(
        select(func.max(SecurityEvent.created_at)).where(
            SecurityEvent.user_id == user.id, SecurityEvent.event_type == LOGIN_SUCCESS
        )
    )
    if last_success is not None:
        last_success = last_success if last_success.tzinfo else last_success.replace(tzinfo=timezone.utc)
        window_start = max(window_start, last_success)
    return _count(
        db,
        SecurityEvent.user_id == user.id,
        SecurityEvent.event_type == LOGIN_FAILED,
        SecurityEvent.created_at > window_start,
    )


def is_locked(db: Session, user: User) -> bool:
    return failed_logins_since_last_success(db, user) >= settings.LOCKOUT_THRESHOLD


# ---------------------------------------------------------------- detection
def _flag_once(db: Session, event_type: str, window_minutes: int, *, user_id=None, ip=None, **kwargs) -> None:
    """Record a suspicious event unless the same one was already flagged recently."""
    conditions = [SecurityEvent.event_type == event_type, _recent(window_minutes)]
    if user_id:
        conditions.append(SecurityEvent.user_id == user_id)
    if ip:
        conditions.append(SecurityEvent.ip_address == ip)
    if _count(db, *conditions) == 0:
        record_event(db, event_type, user_id=user_id, ip=ip, commit=False, **kwargs)


def after_failed_login(db: Session, request, user: User | None, email: str) -> None:
    ip = get_client_ip(request)
    if user is not None:
        failures = failed_logins_since_last_success(db, user)
        if failures >= settings.LOCKOUT_THRESHOLD:
            _flag_once(db, ACCOUNT_LOCKED, settings.LOCKOUT_MINUTES, user_id=user.id, email=user.email, ip=ip,
                       severity="warning", reason=f"{failures} failed logins; locked for {settings.LOCKOUT_MINUTES} minutes")
            _flag_once(db, SUSPICIOUS_FAILED_LOGINS, 60, user_id=user.id, email=user.email,
                       severity="warning", reason=f"{failures} failed logins in a short time")
        distinct_ips = db.scalar(
            select(func.count(func.distinct(SecurityEvent.ip_address))).where(
                SecurityEvent.user_id == user.id, SecurityEvent.event_type == LOGIN_FAILED, _recent(60)
            )
        ) or 0
        if distinct_ips >= 3:
            _flag_once(db, SUSPICIOUS_MANY_IPS, 60, user_id=user.id, email=user.email, severity="warning",
                       reason=f"Failed logins from {distinct_ips} different IPs within an hour")

    distinct_accounts = db.scalar(
        select(func.count(func.distinct(SecurityEvent.email))).where(
            SecurityEvent.ip_address == ip, SecurityEvent.event_type == LOGIN_FAILED, _recent(60)
        )
    ) or 0
    if distinct_accounts >= 3:
        _flag_once(db, SUSPICIOUS_CREDENTIAL_STUFFING, 60, ip=ip, severity="critical",
                   reason=f"Failed logins for {distinct_accounts} different accounts from one IP within an hour")
    db.commit()


def after_successful_login(db: Session, request, user: User) -> None:
    ip = get_client_ip(request)
    earlier_logins = _count(db, SecurityEvent.user_id == user.id, SecurityEvent.event_type == LOGIN_SUCCESS)
    seen_here = _count(
        db, SecurityEvent.user_id == user.id, SecurityEvent.event_type == LOGIN_SUCCESS, SecurityEvent.ip_address == ip
    )
    # (counts include the success just recorded)
    if earlier_logins > 1 and seen_here == 1:
        record_event(db, SUSPICIOUS_NEW_IP, user=user, ip=ip, severity="info", commit=False,
                     reason="Login from an IP address not seen before for this account")
    db.commit()


def after_registration(db: Session, request) -> None:
    ip = get_client_ip(request)
    registrations = _count(db, SecurityEvent.event_type == REGISTER, SecurityEvent.ip_address == ip, _recent(24 * 60))
    if registrations >= 3:
        _flag_once(db, SUSPICIOUS_REGISTRATIONS, 24 * 60, ip=ip, severity="warning",
                   reason=f"{registrations} accounts registered from one IP within 24 hours")
        db.commit()


def after_blocked_request(db: Session, ip: str) -> None:
    blocked = _count(db, SecurityEvent.event_type == BLOCKED_IP_REQUEST, SecurityEvent.ip_address == ip, _recent(10))
    if blocked >= 20:
        _flag_once(db, SUSPICIOUS_BLOCKED_REQUESTS, 60, ip=ip, severity="warning",
                   reason="Repeated requests from a blocked IP")
        db.commit()
