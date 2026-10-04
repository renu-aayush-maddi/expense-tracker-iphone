"""Roles and permissions.

Roles are stored on the user (users.role). What each role may do is defined
HERE, on the server – the frontend only uses this list to hide buttons.
To add a role later (e.g. "support"), add it to Role and ROLE_PERMISSIONS.
"""

from enum import StrEnum


class Role(StrEnum):
    USER = "user"
    READ_ONLY_ADMIN = "read_only_admin"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


ADMIN_ROLES = {Role.READ_ONLY_ADMIN, Role.ADMIN, Role.SUPER_ADMIN}


class Permission(StrEnum):
    DASHBOARD_VIEW = "dashboard:view"
    USERS_VIEW = "users:view"
    USERS_MANAGE = "users:manage"  # edit profile, block/disable, force logout, reset password
    USERS_DELETE = "users:delete"
    TRANSACTIONS_VIEW = "transactions:view"
    TRANSACTIONS_MANAGE = "transactions:manage"  # soft-delete / restore
    AUDIT_VIEW = "audit:view"
    SECURITY_VIEW = "security:view"  # security events, sessions, IPs
    SECURITY_MANAGE = "security:manage"  # revoke sessions, block IPs
    SYSTEM_VIEW = "system:view"
    REPORTS_VIEW = "reports:view"
    DATA_EXPORT = "data:export"  # CSV exports
    ADMINS_MANAGE = "admins:manage"  # grant/change/remove admin roles


_READ_ONLY = {
    Permission.DASHBOARD_VIEW,
    Permission.USERS_VIEW,
    Permission.TRANSACTIONS_VIEW,
    Permission.AUDIT_VIEW,
    Permission.SECURITY_VIEW,
    Permission.SYSTEM_VIEW,
    Permission.REPORTS_VIEW,
}
_ADMIN = _READ_ONLY | {
    Permission.USERS_MANAGE,
    Permission.TRANSACTIONS_MANAGE,
    Permission.SECURITY_MANAGE,
    Permission.DATA_EXPORT,
}

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    Role.USER: frozenset(),
    Role.READ_ONLY_ADMIN: frozenset(_READ_ONLY),
    Role.ADMIN: frozenset(_ADMIN),
    Role.SUPER_ADMIN: frozenset(Permission),  # everything
}

# Higher number = more powerful. Used so admins can't act on equal/higher roles.
ROLE_RANK = {Role.USER: 0, Role.READ_ONLY_ADMIN: 1, Role.ADMIN: 2, Role.SUPER_ADMIN: 3}


def permissions_for(role: str) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def is_admin(role: str) -> bool:
    return role in ADMIN_ROLES


def can_act_on(actor_role: str, target_role: str) -> bool:
    """Super admins can act on anyone; other admins only on plain users."""
    if actor_role == Role.SUPER_ADMIN:
        return True
    return target_role == Role.USER and ROLE_RANK.get(actor_role, 0) >= ROLE_RANK[Role.ADMIN]
