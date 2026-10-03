"""Database engine and session.

Only DATABASE_URL decides which PostgreSQL provider is used (Supabase, Render,
Neon, local...). Switching providers = changing one environment variable.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def build_engine(url: str):
    if url.startswith("sqlite"):
        # Used only by the test-suite.
        from sqlalchemy.pool import StaticPool

        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

    return create_engine(
        url,
        pool_pre_ping=True,  # survive dropped connections (Supabase pooler, Render sleep)
        pool_size=5,
        max_overflow=5,
        pool_recycle=300,
        # Disable server-side prepared statements so the app also works through
        # PgBouncer / Supabase "transaction" pooler.
        connect_args={"prepare_threshold": None},
    )


engine = build_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
