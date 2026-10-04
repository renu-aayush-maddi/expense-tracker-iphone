"""Admin: audit logs (read-only, append-only) and security events."""

import csv
import io
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.admin.common import day_end, day_start, paginate
from app.api.deps import require_permission
from app.core.client_ip import describe_user_agent
from app.core.permissions import Permission, permissions_for
from app.db.session import get_db
from app.models import AuditLog, SecurityEvent, User
from app.schemas.admin import AuditLogOut, Page, SecurityEventOut
from app.services import audit_service, security_service

router = APIRouter(tags=["admin: logs"])

AUDIT_VIEW = Depends(require_permission(Permission.AUDIT_VIEW))
SECURITY_VIEW = Depends(require_permission(Permission.SECURITY_VIEW))


def _audit_query(q, action, actor, target, resource_type, result, date_from, date_to, sort_order):
    query = select(AuditLog)
    if q:
        term = f"%{q}%"
        query = query.where(or_(AuditLog.action.ilike(term), AuditLog.actor_email.ilike(term),
                                AuditLog.target_email.ilike(term), AuditLog.resource_id.ilike(term),
                                AuditLog.ip_address.ilike(term)))
    if action:
        query = query.where(AuditLog.action == action)
    if actor:
        query = query.where(AuditLog.actor_email.ilike(f"%{actor}%"))
    if target:
        query = query.where(AuditLog.target_email.ilike(f"%{target}%"))
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if result:
        query = query.where(AuditLog.result == result)
    if date_from:
        query = query.where(AuditLog.created_at >= day_start(date_from))
    if date_to:
        query = query.where(AuditLog.created_at < day_end(date_to))
    order = AuditLog.created_at.asc() if sort_order == "asc" else AuditLog.created_at.desc()
    return query.order_by(order, AuditLog.id)


AUDIT_FILTERS = dict(
    q=Query(default=None, max_length=100),
    action=Query(default=None, max_length=60),
    actor=Query(default=None, max_length=100),
    target=Query(default=None, max_length=100),
    resource_type=Query(default=None, max_length=40),
)


@router.get("/audit-logs", response_model=Page[AuditLogOut])
def list_audit_logs(
    q: str | None = AUDIT_FILTERS["q"],
    action: str | None = AUDIT_FILTERS["action"],
    actor: str | None = AUDIT_FILTERS["actor"],
    target: str | None = AUDIT_FILTERS["target"],
    resource_type: str | None = AUDIT_FILTERS["resource_type"],
    result: Literal["success", "failure"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    admin: User = AUDIT_VIEW,
    db: Session = Depends(get_db),
):
    query = _audit_query(q, action, actor, target, resource_type, result, date_from, date_to, sort_order)
    rows, total, pages = paginate(db, query, page, page_size)
    return {"items": [AuditLogOut.model_validate(r[0]) for r in rows], "total": total, "page": page,
            "page_size": page_size, "pages": pages}


@router.get("/audit-logs/actions")
def audit_actions(admin: User = AUDIT_VIEW, db: Session = Depends(get_db)):
    return sorted(db.scalars(select(AuditLog.action).distinct()).all())


@router.get("/audit-logs/export.csv")
def export_audit_logs(
    request: Request,
    q: str | None = AUDIT_FILTERS["q"],
    action: str | None = AUDIT_FILTERS["action"],
    actor: str | None = AUDIT_FILTERS["actor"],
    target: str | None = AUDIT_FILTERS["target"],
    resource_type: str | None = AUDIT_FILTERS["resource_type"],
    result: Literal["success", "failure"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    admin: User = Depends(require_permission(Permission.DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    if Permission.AUDIT_VIEW not in permissions_for(admin.role):  # needs both export AND audit access
        raise HTTPException(status_code=403, detail="Your admin role doesn't allow this action.")
    rows = db.scalars(_audit_query(q, action, actor, target, resource_type, result, date_from, date_to, "desc").limit(10000)).all()
    audit_service.record(db, "AUDIT_LOG_EXPORTED", actor=admin, request=request, resource_type="report",
                         details={"rows": len(rows), "filters": {k: v for k, v in dict(q=q, action=action, actor=actor,
                                  target=target, date_from=str(date_from or ""), date_to=str(date_to or "")).items() if v}})
    return csv_response(
        "audit-logs.csv",
        ["Time (UTC)", "Actor", "Actor role", "Action", "Resource", "Resource ID", "Target", "Result", "IP", "Details"],
        [[r.created_at.isoformat(), r.actor_email, r.actor_role, r.action, r.resource_type, r.resource_id,
          r.target_email, r.result, r.ip_address, r.details] for r in rows],
    )


@router.get("/audit-logs/{log_id}", response_model=AuditLogOut)
def get_audit_log(log_id: uuid.UUID, admin: User = AUDIT_VIEW, db: Session = Depends(get_db)):
    entry = db.get(AuditLog, log_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Audit log entry not found.")
    return entry
# Note: there are deliberately NO update/delete endpoints for audit logs.


@router.get("/security-events", response_model=Page[SecurityEventOut])
def list_security_events(
    user: str | None = Query(default=None, max_length=100, description="email contains"),
    user_id: uuid.UUID | None = None,
    ip: str | None = Query(default=None, max_length=45),
    event_type: str | None = Query(default=None, max_length=50),
    category: Literal["auth", "suspicious", "all"] = "all",
    success: bool | None = None,
    severity: Literal["info", "warning", "critical"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    admin: User = SECURITY_VIEW,
    db: Session = Depends(get_db),
):
    query = select(SecurityEvent)
    if user:
        query = query.where(SecurityEvent.email.ilike(f"%{user}%"))
    if user_id:
        query = query.where(SecurityEvent.user_id == user_id)
    if ip:
        query = query.where(SecurityEvent.ip_address == ip.strip())
    if event_type:
        query = query.where(SecurityEvent.event_type == event_type)
    if category == "auth":
        query = query.where(SecurityEvent.event_type.in_(security_service.AUTH_TYPES))
    elif category == "suspicious":
        query = query.where(SecurityEvent.event_type.in_(security_service.SUSPICIOUS_TYPES))
    if success is not None:
        query = query.where(SecurityEvent.success.is_(success))
    if severity:
        query = query.where(SecurityEvent.severity == severity)
    if date_from:
        query = query.where(SecurityEvent.created_at >= day_start(date_from))
    if date_to:
        query = query.where(SecurityEvent.created_at < day_end(date_to))
    rows, total, pages = paginate(db, query.order_by(SecurityEvent.created_at.desc(), SecurityEvent.id), page, page_size)
    items = []
    for (event,) in rows:
        out = SecurityEventOut.model_validate(event)
        out.device = describe_user_agent(event.user_agent) if event.user_agent else None
        items.append(out)
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


@router.get("/security-events/types")
def security_event_types(admin: User = SECURITY_VIEW, db: Session = Depends(get_db)):
    return sorted(db.scalars(select(SecurityEvent.event_type).distinct()).all())


@router.get("/security-events/summary")
def security_summary(admin: User = SECURITY_VIEW, db: Session = Depends(get_db)):
    """Counts of suspicious events in the last 7 days, by type."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = db.execute(
        select(SecurityEvent.event_type, SecurityEvent.severity, func.count())
        .where(SecurityEvent.event_type.in_(security_service.SUSPICIOUS_TYPES), SecurityEvent.created_at >= since)
        .group_by(SecurityEvent.event_type, SecurityEvent.severity)
    ).all()
    return [{"event_type": t, "severity": s, "count": c} for t, s, c in rows]


def csv_cell(value) -> str:
    """Stop spreadsheet formula injection."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_cell(v) for v in row])
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
