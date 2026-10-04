"""Admin: sessions, IP addresses and the IP blocklist."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.admin.common import paginate
from app.api.deps import require_permission
from app.core.client_ip import describe_user_agent, get_client_ip
from app.core.permissions import Permission, can_act_on
from app.db.session import get_db
from app.models import IpBlock, SecurityEvent, User, UserSession
from app.schemas.admin import IpBlockOut, IpBlockRequest, IpSummary, OptionalReasonRequest, Page, SecurityEventOut, SessionOut
from app.services import admin_service, audit_service, ip_block_service, security_service, session_service

router = APIRouter(tags=["admin: security"])

VIEW = Depends(require_permission(Permission.SECURITY_VIEW))
MANAGE = Depends(require_permission(Permission.SECURITY_MANAGE))


# ---------------------------------------------------------------- sessions
@router.get("/sessions", response_model=Page[SessionOut])
def list_sessions(
    state: Literal["active", "all"] = "active",
    user: str | None = Query(default=None, max_length=100),
    user_id: uuid.UUID | None = None,
    ip: str | None = Query(default=None, max_length=45),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    admin: User = VIEW,
    db: Session = Depends(get_db),
):
    query = select(UserSession, User).join(User, User.id == UserSession.user_id)
    if state == "active":
        query = query.where(session_service.active_sessions_filter())
    if user:
        query = query.where(User.email.ilike(f"%{user}%"))
    if user_id:
        query = query.where(UserSession.user_id == user_id)
    if ip:
        query = query.where(UserSession.ip_address == ip.strip())
    rows, total, pages = paginate(db, query.order_by(UserSession.last_seen_at.desc(), UserSession.id), page, page_size)
    items = [admin_service.session_out(s, u) for s, u in rows]
    if state == "active":  # admin idle timeout isn't expressible in SQL; drop those here
        items = [i for i in items if i["status"] == "active"]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


@router.post("/sessions/{session_id}/revoke")
def revoke_session(session_id: uuid.UUID, payload: OptionalReasonRequest, request: Request, admin: User = MANAGE,
                   db: Session = Depends(get_db)):
    session = db.get(UserSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    owner = db.get(User, session.user_id)
    if owner.id != admin.id and not can_act_on(admin.role, owner.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can manage other administrators.")
    session_service.revoke(db, session, reason="admin_revoked", by=admin)
    security_service.record_event(db, security_service.SESSION_REVOKED, request=request, user=owner,
                                  reason="session revoked by admin", commit=False)
    audit_service.record(db, "SESSION_REVOKED", actor=admin, request=request, resource_type="session",
                         resource_id=session.id, target=owner,
                         details={"reason": payload.reason, "session_ip": session.ip_address}, commit=False)
    db.commit()
    return {"revoked": True}


@router.post("/sessions/revoke-by-ip")
def revoke_sessions_by_ip(payload: IpBlockRequest, request: Request, admin: User = MANAGE, db: Session = Depends(get_db)):
    """Revoke every active session from one IP (e.g. a suspicious network). Admins' own sessions are kept."""
    ip = _valid_ip(payload.ip_address)
    rows = db.execute(
        select(UserSession, User).join(User, User.id == UserSession.user_id)
        .where(UserSession.ip_address == ip, session_service.active_sessions_filter())
    ).all()
    revoked = 0
    for session, owner in rows:
        if owner.id == admin.id or not can_act_on(admin.role, owner.role):
            continue
        session_service.revoke(db, session, reason="admin_revoked_ip", by=admin)
        revoked += 1
    audit_service.record(db, "SESSIONS_REVOKED_BY_IP", actor=admin, request=request, resource_type="ip", resource_id=ip,
                         details={"reason": payload.reason, "sessions_revoked": revoked}, commit=False)
    db.commit()
    return {"sessions_revoked": revoked}


# ---------------------------------------------------------------- IP addresses
def _valid_ip(value: str) -> str:
    try:
        return ip_block_service.normalize_ip(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Enter a single valid IPv4 or IPv6 address.")


@router.get("/ip-addresses", response_model=Page[IpSummary])
def list_ip_addresses(
    q: str | None = Query(default=None, max_length=45),
    blocked: bool | None = None,
    sort_by: Literal["last_seen", "events", "failed_logins", "users"] = "last_seen",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    admin: User = VIEW,
    db: Session = Depends(get_db),
):
    blocked_ips = {b.ip_address for b in db.scalars(ip_block_service.active_blocks_query()).all()}
    success = func.sum(case((SecurityEvent.event_type == security_service.LOGIN_SUCCESS, 1), else_=0))
    failed = func.sum(case((SecurityEvent.event_type == security_service.LOGIN_FAILED, 1), else_=0))
    users = func.count(func.distinct(SecurityEvent.user_id))
    events = func.count()
    query = (
        select(SecurityEvent.ip_address, func.min(SecurityEvent.created_at), func.max(SecurityEvent.created_at),
               users, events, success, failed)
        .where(SecurityEvent.ip_address.is_not(None))
        .group_by(SecurityEvent.ip_address)
    )
    if q:
        query = query.where(SecurityEvent.ip_address.ilike(f"%{q.strip()}%"))
    if blocked is True:
        query = query.where(SecurityEvent.ip_address.in_(blocked_ips or {""}))
    elif blocked is False and blocked_ips:
        query = query.where(SecurityEvent.ip_address.not_in(blocked_ips))
    order = {"last_seen": func.max(SecurityEvent.created_at), "events": events, "failed_logins": failed, "users": users}[sort_by]
    rows, total, pages = paginate(db, query.order_by(order.desc(), SecurityEvent.ip_address), page, page_size)
    items = [
        {"ip_address": ip, "first_seen": first, "last_seen": last, "users": u, "events": e,
         "successful_logins": int(s or 0), "failed_logins": int(f or 0), "blocked": ip in blocked_ips}
        for ip, first, last, u, e, s, f in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


@router.get("/ip-addresses/{ip}")
def inspect_ip(ip: str, admin: User = VIEW, db: Session = Depends(get_db)):
    ip = _valid_ip(ip)
    user_rows = db.execute(
        select(User.id, User.email, User.status, func.count(), func.max(SecurityEvent.created_at))
        .join(User, User.id == SecurityEvent.user_id)
        .where(SecurityEvent.ip_address == ip)
        .group_by(User.id, User.email, User.status)
        .order_by(func.max(SecurityEvent.created_at).desc())
        .limit(100)
    ).all()
    events = db.scalars(
        select(SecurityEvent).where(SecurityEvent.ip_address == ip).order_by(SecurityEvent.created_at.desc()).limit(100)
    ).all()
    history = db.scalars(select(IpBlock).where(IpBlock.ip_address == ip).order_by(IpBlock.created_at.desc())).all()
    active = ip_block_service.find_active(db, ip)
    return {
        "ip_address": ip,
        "blocked": active is not None,
        "active_block": IpBlockOut.model_validate(active) if active else None,
        "block_history": [IpBlockOut.model_validate(b) for b in history],
        "users": [{"id": i, "email": e, "status": s, "events": c, "last_seen": last} for i, e, s, c, last in user_rows],
        "events": [SecurityEventOut.model_validate(e).model_copy(update={"device": describe_user_agent(e.user_agent)})
                   for e in events],
    }


@router.get("/ip-blocks", response_model=Page[IpBlockOut])
def list_ip_blocks(state: Literal["active", "all"] = "active", page: int = Query(default=1, ge=1),
                   page_size: int = Query(default=50, ge=1, le=200), admin: User = VIEW, db: Session = Depends(get_db)):
    query = ip_block_service.active_blocks_query() if state == "active" else select(IpBlock)
    rows, total, pages = paginate(db, query.order_by(IpBlock.created_at.desc()), page, page_size)
    return {"items": [IpBlockOut.model_validate(r[0]) for r in rows], "total": total, "page": page,
            "page_size": page_size, "pages": pages}


@router.post("/ip-blocks", response_model=IpBlockOut, status_code=status.HTTP_201_CREATED)
def block_ip(payload: IpBlockRequest, request: Request, admin: User = MANAGE, db: Session = Depends(get_db)):
    ip = _valid_ip(payload.ip_address)
    # Safeguard: never let an admin lock themselves out.
    if ip == get_client_ip(request):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You can't block the IP address you're using right now.")
    if ip_block_service.find_active(db, ip):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This IP is already blocked.")
    block = IpBlock(
        ip_address=ip,
        reason=payload.reason.strip(),
        blocked_by_id=admin.id,
        blocked_by_email=admin.email,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=payload.expires_hours) if payload.expires_hours else None,
    )
    db.add(block)
    db.flush()
    audit_service.record(db, "IP_BLOCKED", actor=admin, request=request, resource_type="ip", resource_id=ip,
                         details={"reason": block.reason, "expires_hours": payload.expires_hours}, commit=False)
    db.commit()
    ip_block_service.invalidate_cache()
    return block


@router.post("/ip-blocks/{block_id}/unblock", response_model=IpBlockOut)
def unblock_ip(block_id: uuid.UUID, payload: OptionalReasonRequest, request: Request, admin: User = MANAGE,
               db: Session = Depends(get_db)):
    block = db.get(IpBlock, block_id)
    if block is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Block not found.")
    if block.unblocked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already unblocked.")
    block.unblocked_at = datetime.now(timezone.utc)
    block.unblocked_by_email = admin.email
    audit_service.record(db, "IP_UNBLOCKED", actor=admin, request=request, resource_type="ip", resource_id=block.ip_address,
                         details={"reason": payload.reason, "originally_blocked_by": block.blocked_by_email}, commit=False)
    db.commit()
    ip_block_service.invalidate_cache()
    return block


