"""All admin endpoints live under /api/admin and every one of them checks the
caller's admin role/permission on the server (see api/deps.require_permission)."""

from fastapi import APIRouter

from app.api.admin import logs, overview, security, transactions, users

router = APIRouter(prefix="/admin")
router.include_router(overview.router)
router.include_router(users.router)
router.include_router(transactions.router)
router.include_router(logs.router)
router.include_router(security.router)
