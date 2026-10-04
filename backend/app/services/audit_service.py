"""Audit log: who did what, to whom, from where. Append-only."""

import logging
import uuid

from sqlalchemy.orm import Session

from app.core.client_ip import get_client_ip, get_user_agent
from app.models import AuditLog, User

audit_logger = logging.getLogger("audit")

# Never let secrets end up in audit metadata, whatever a caller passes.
_SECRET_KEYS = {"password", "new_password", "current_password", "token", "access_token", "hashed_password", "secret"}


def _clean(details: dict | None) -> dict:
    if not details:
        return {}
    return {k: ("[redacted]" if k.lower() in _SECRET_KEYS else v) for k, v in details.items()}


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    request=None,
    resource_type: str | None = None,
    resource_id: str | uuid.UUID | None = None,
    target: User | None = None,
    target_user_id: uuid.UUID | None = None,
    result: str = "success",
    details: dict | None = None,
    commit: bool = True,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        actor_role=actor.role if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        target_user_id=target.id if target else target_user_id,
        target_email=target.email if target else None,
        result=result,
        ip_address=get_client_ip(request) if request is not None else None,
        user_agent=get_user_agent(request) if request is not None else None,
        details=_clean(details),
    )
    db.add(entry)
    if commit:
        db.commit()
    # Separate log stream for audit events (ids only, no personal data).
    audit_logger.info(
        "%s actor=%s target=%s resource=%s:%s result=%s",
        action, entry.actor_user_id, entry.target_user_id, resource_type, entry.resource_id, result,
    )
    return entry
