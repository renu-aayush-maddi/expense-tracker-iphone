from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import CATEGORIES, PAYMENT_METHODS, SOURCES
from app.db.session import get_db

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """Used by Render's health check (and handy to wake the free instance)."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/meta")
def meta():
    """Public, non-sensitive app configuration for the frontend."""
    return {
        "categories": CATEGORIES,
        "payment_methods": PAYMENT_METHODS,
        "sources": SOURCES,
        "allow_registration": settings.ALLOW_REGISTRATION,
    }
