"""Create the first super admin safely.

No password ever lives in config or code. Two options:

1. CLI (password typed interactively, hashed with bcrypt):
       python -m app.cli create-admin --email you@example.com
2. INITIAL_SUPER_ADMIN_EMAIL env var: at startup, if NO super admin exists yet,
   the EXISTING account with that email is promoted. Register the account
   normally first. Once a super admin exists, the variable does nothing.
"""

import logging

from sqlalchemy import func, select

from app.core.config import settings
from app.core.permissions import Role
from app.models import User
from app.services import audit_service, session_service

logger = logging.getLogger("app")


def promote_initial_super_admin(session_factory) -> bool:
    email = (settings.INITIAL_SUPER_ADMIN_EMAIL or "").strip().lower()
    if not email:
        return False
    with session_factory() as db:
        if db.scalar(select(func.count()).select_from(User).where(User.role == Role.SUPER_ADMIN)):
            return False
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            logger.warning("INITIAL_SUPER_ADMIN_EMAIL is set but no account with that email exists yet")
            return False
        user.role = Role.SUPER_ADMIN
        session_service.revoke_all(db, user.id, reason="role_changed")  # log in again with admin limits
        audit_service.record(db, "ADMIN_BOOTSTRAPPED", target=user, resource_type="user", resource_id=user.id,
                             details={"via": "INITIAL_SUPER_ADMIN_EMAIL"}, commit=False)
        db.commit()
        logger.info("Promoted the initial super admin")
        return True
