"""Admin: user management (/api/admin/users) and admin management (/api/admin/admins)."""

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin.common import confirm_password, day_end, day_start, ensure_can_act, get_target_user, paginate
from app.api.deps import require_permission
from app.core.permissions import Permission, Role
from app.core.security import generate_temporary_password
from app.db.session import get_db
from app.models import ApiToken, User
from app.models.user import (
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_DELETED,
    STATUS_DISABLED,
    STATUS_SUSPENDED,
    USER_STATUSES,
)
from app.schemas.admin import (
    AddAdminRequest,
    AdminUserDetail,
    AdminUserRow,
    AdminUserUpdate,
    OptionalReasonRequest,
    Page,
    PasswordConfirmRequest,
    ReasonRequest,
    RoleChangeRequest,
    SecurityEventOut,
    TemporaryPasswordOut,
)
from app.services import admin_service, audit_service, auth_service, security_service, session_service

router = APIRouter(tags=["admin: users"])

VIEW = Depends(require_permission(Permission.USERS_VIEW))
MANAGE = Depends(require_permission(Permission.USERS_MANAGE))


@router.get("/users", response_model=Page[AdminUserRow])
def list_users(
    q: str | None = Query(default=None, max_length=100),
    role: Literal["user", "read_only_admin", "admin", "super_admin"] | None = None,
    status_filter: Literal["active", "disabled", "suspended", "blocked", "deleted"] | None = Query(default=None, alias="status"),
    created_from: date | None = None,
    created_to: date | None = None,
    active_from: date | None = None,
    active_to: date | None = None,
    sort_by: Literal["created", "email", "last_login", "last_activity", "role", "status", "transactions", "total"] = "created",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    admin: User = VIEW,
    db: Session = Depends(get_db),
):
    query = admin_service.users_query(
        q=q,
        role=role,
        status_filter=status_filter,
        created_from=day_start(created_from) if created_from else None,
        created_to=day_end(created_to) if created_to else None,
        active_from=day_start(active_from) if active_from else None,
        active_to=day_end(active_to) if active_to else None,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    rows, total, pages = paginate(db, query, page, page_size)
    return {"items": [admin_service.user_row(*r) for r in rows], "total": total, "page": page,
            "page_size": page_size, "pages": pages}


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def get_user(user_id: uuid.UUID, request: Request, admin: User = VIEW, db: Session = Depends(get_db)):
    user = get_target_user(db, user_id)
    audit_service.record(db, "USER_VIEWED", actor=admin, request=request, resource_type="user",
                         resource_id=user.id, target=user)
    return admin_service.user_detail(db, user)


@router.get("/users/{user_id}/activity")
def user_activity(user_id: uuid.UUID, admin: User = VIEW, db: Session = Depends(get_db)):
    return admin_service.activity_timeline(db, get_target_user(db, user_id))


@router.get("/users/{user_id}/security")
def user_security(user_id: uuid.UUID, admin: User = VIEW, db: Session = Depends(get_db)):
    data = admin_service.user_security(db, get_target_user(db, user_id))
    data["events"] = [SecurityEventOut.model_validate(e) for e in data["events"]]
    return data


@router.get("/users/{user_id}/finance")
def user_finance(
    user_id: uuid.UUID,
    admin: User = Depends(require_permission(Permission.TRANSACTIONS_VIEW)),
    db: Session = Depends(get_db),
):
    return admin_service.user_finance(db, get_target_user(db, user_id))


@router.patch("/users/{user_id}", response_model=AdminUserDetail)
def update_user(
    user_id: uuid.UUID, payload: AdminUserUpdate, request: Request, admin: User = MANAGE, db: Session = Depends(get_db)
):
    user = get_target_user(db, user_id)
    ensure_can_act(admin, user)
    changes = payload.model_dump(exclude_unset=True)
    if "email" in changes and changes["email"]:
        new_email = changes["email"].lower()
        existing = auth_service.get_user_by_email(db, new_email)
        if existing and existing.id != user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another account already uses this email.")
        changes["email"] = new_email
    elif "email" in changes:
        changes.pop("email")  # email can't be cleared
    diff = {field: {"from": getattr(user, field), "to": value} for field, value in changes.items() if getattr(user, field) != value}
    for field, value in changes.items():
        setattr(user, field, value)
    if diff:
        audit_service.record(db, "USER_UPDATED", actor=admin, request=request, resource_type="user",
                             resource_id=user.id, target=user, details={"changes": diff}, commit=False)
    db.commit()
    return admin_service.user_detail(db, user)


def _status_action(new_status: str, action: str, require_reason: bool):
    body_model = ReasonRequest if require_reason else OptionalReasonRequest

    def endpoint(user_id: uuid.UUID, payload: body_model, request: Request, admin: User = MANAGE,  # type: ignore[valid-type]
                 db: Session = Depends(get_db)):
        user = get_target_user(db, user_id)
        ensure_can_act(admin, user)
        admin_service.change_status(db, request, admin, user, new_status, payload.reason, action)
        return admin_service.user_detail(db, user)

    return endpoint


router.post("/users/{user_id}/block", response_model=AdminUserDetail)(_status_action(STATUS_BLOCKED, "USER_BLOCKED", True))
router.post("/users/{user_id}/unblock", response_model=AdminUserDetail)(_status_action(STATUS_ACTIVE, "USER_UNBLOCKED", False))
router.post("/users/{user_id}/disable", response_model=AdminUserDetail)(_status_action(STATUS_DISABLED, "USER_DISABLED", True))
router.post("/users/{user_id}/enable", response_model=AdminUserDetail)(_status_action(STATUS_ACTIVE, "USER_ENABLED", False))
router.post("/users/{user_id}/suspend", response_model=AdminUserDetail)(_status_action(STATUS_SUSPENDED, "USER_SUSPENDED", True))


@router.post("/users/{user_id}/force-logout")
def force_logout(user_id: uuid.UUID, payload: OptionalReasonRequest, request: Request, admin: User = MANAGE,
                 db: Session = Depends(get_db)):
    user = get_target_user(db, user_id)
    ensure_can_act(admin, user)
    revoked = session_service.revoke_all(db, user.id, reason="admin_force_logout", by=admin)
    security_service.record_event(db, security_service.SESSION_REVOKED, request=request, user=user,
                                  reason=f"{revoked} session(s) revoked by admin", commit=False)
    audit_service.record(db, "USER_FORCE_LOGOUT", actor=admin, request=request, resource_type="user",
                         resource_id=user.id, target=user, details={"sessions_revoked": revoked, "reason": payload.reason},
                         commit=False)
    db.commit()
    return {"sessions_revoked": revoked}


@router.post("/users/{user_id}/reset-password", response_model=TemporaryPasswordOut)
def reset_password(user_id: uuid.UUID, payload: PasswordConfirmRequest, request: Request, admin: User = MANAGE,
                   db: Session = Depends(get_db)):
    """Sets a one-time temporary password (shown once). The user must change it at next login."""
    user = get_target_user(db, user_id)
    ensure_can_act(admin, user)
    confirm_password(db, request, admin, payload.password)
    temporary = generate_temporary_password()
    auth_service.set_password(user, temporary)
    user.must_change_password = True
    revoked = session_service.revoke_all(db, user.id, reason="password_reset", by=admin)
    security_service.record_event(db, security_service.PASSWORD_RESET, request=request, user=user, success=True,
                                  reason="reset by admin", commit=False)
    audit_service.record(db, "PASSWORD_RESET_BY_ADMIN", actor=admin, request=request, resource_type="user",
                         resource_id=user.id, target=user, details={"sessions_revoked": revoked, "reason": payload.reason},
                         commit=False)
    db.commit()
    return {"temporary_password": temporary,
            "message": "Give this to the user securely. It is shown only once; they must change it when they log in."}


@router.post("/users/{user_id}/delete", response_model=AdminUserDetail)
def delete_user(user_id: uuid.UUID, payload: PasswordConfirmRequest, request: Request,
                admin: User = Depends(require_permission(Permission.USERS_DELETE)), db: Session = Depends(get_db)):
    """Soft delete: the account can't be used, its data is kept (and can be restored)."""
    user = get_target_user(db, user_id)
    ensure_can_act(admin, user)
    confirm_password(db, request, admin, payload.password)
    if user.status == STATUS_DELETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This account is already deleted.")
    tokens = db.scalars(select(ApiToken).where(ApiToken.user_id == user.id)).all()
    for token in tokens:  # import tokens stop working too
        db.delete(token)
    admin_service.change_status(db, request, admin, user, STATUS_DELETED, payload.reason, "USER_DELETED")
    return admin_service.user_detail(db, user)


@router.post("/users/{user_id}/restore", response_model=AdminUserDetail)
def restore_user(user_id: uuid.UUID, payload: PasswordConfirmRequest, request: Request,
                 admin: User = Depends(require_permission(Permission.USERS_DELETE)), db: Session = Depends(get_db)):
    user = get_target_user(db, user_id)
    ensure_can_act(admin, user)
    confirm_password(db, request, admin, payload.password)
    if user.status != STATUS_DELETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This account isn't deleted.")
    admin_service.change_status(db, request, admin, user, STATUS_ACTIVE, payload.reason, "USER_RESTORED")
    return admin_service.user_detail(db, user)


# ---------------------------------------------------------------- roles & admins (super admin)
ADMINS = Depends(require_permission(Permission.ADMINS_MANAGE))


def _set_role(db: Session, request: Request, admin: User, target: User, role: str, reason: str | None) -> None:
    if target.id == admin.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can't change your own role.")
    if target.status == STATUS_DELETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This account is deleted.")
    if target.role == role:
        return
    if target.role == Role.SUPER_ADMIN:
        admin_service.ensure_other_super_admin(db, target)
    old_role = target.role
    target.role = role
    # New privileges = new login: end the user's sessions so limits (e.g. admin timeouts) apply.
    revoked = session_service.revoke_all(db, target.id, reason="role_changed", by=admin)
    audit_service.record(db, "USER_ROLE_CHANGED", actor=admin, request=request, resource_type="user",
                         resource_id=target.id, target=target,
                         details={"from": old_role, "to": role, "reason": reason, "sessions_revoked": revoked}, commit=False)
    db.commit()


@router.post("/users/{user_id}/role", response_model=AdminUserDetail)
def change_role(user_id: uuid.UUID, payload: RoleChangeRequest, request: Request, admin: User = ADMINS,
                db: Session = Depends(get_db)):
    user = get_target_user(db, user_id)
    confirm_password(db, request, admin, payload.password)
    _set_role(db, request, admin, user, payload.role, payload.reason)
    return admin_service.user_detail(db, user)


@router.get("/admins", response_model=Page[AdminUserRow])
def list_admins(page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100),
                admin: User = ADMINS, db: Session = Depends(get_db)):
    rows, total, pages = paginate(db, admin_service.users_query(admins_only=True, sort_by="role"), page, page_size)
    return {"items": [admin_service.user_row(*r) for r in rows], "total": total, "page": page,
            "page_size": page_size, "pages": pages}


@router.post("/admins", response_model=AdminUserDetail, status_code=status.HTTP_201_CREATED)
def add_admin(payload: AddAdminRequest, request: Request, admin: User = ADMINS, db: Session = Depends(get_db)):
    """Give an EXISTING account an admin role (they register normally first)."""
    confirm_password(db, request, admin, payload.password)
    user = auth_service.get_user_by_email(db, payload.email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No account with that email. Ask them to register first.")
    if user.status != STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only active accounts can become admins.")
    _set_role(db, request, admin, user, payload.role, payload.reason)
    return admin_service.user_detail(db, user)


@router.get("/admins/{user_id}/activity")
def admin_activity(user_id: uuid.UUID, admin: User = ADMINS, db: Session = Depends(get_db)):
    """Recent actions performed BY this admin."""
    from app.models import AuditLog
    from app.schemas.admin import AuditLogOut

    target = get_target_user(db, user_id)
    rows = db.scalars(
        select(AuditLog).where(AuditLog.actor_user_id == target.id).order_by(AuditLog.created_at.desc()).limit(100)
    ).all()
    return [AuditLogOut.model_validate(r) for r in rows]


@router.get("/meta/statuses")
def statuses(admin: User = VIEW):
    return {"statuses": USER_STATUSES, "roles": [r.value for r in Role]}


