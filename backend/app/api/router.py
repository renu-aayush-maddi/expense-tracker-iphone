from fastapi import APIRouter

from app.api import auth, imports, meta, settings, stats, transactions

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
# Import routes are registered before /transactions/{id} routes on purpose.
api_router.include_router(imports.router)
api_router.include_router(transactions.router)
api_router.include_router(stats.router)
api_router.include_router(settings.router)
