"""IP blocklist with a short in-memory cache (so every request doesn't hit the DB)."""

import ipaddress
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import IpBlock

CACHE_SECONDS = 30
_cache: dict = {"loaded_at": 0.0, "ips": frozenset()}
_lock = threading.Lock()


def normalize_ip(value: str) -> str:
    """Raises ValueError for anything that isn't a single valid IPv4/IPv6 address."""
    return str(ipaddress.ip_address(value.strip()))


def active_blocks_query():
    now = datetime.now(timezone.utc)
    return select(IpBlock).where(
        IpBlock.unblocked_at.is_(None), or_(IpBlock.expires_at.is_(None), IpBlock.expires_at > now)
    )


def invalidate_cache() -> None:
    with _lock:
        _cache["loaded_at"] = 0.0


def is_blocked(db_factory, ip: str) -> bool:
    now = time.monotonic()
    with _lock:
        fresh = now - _cache["loaded_at"] < CACHE_SECONDS
        ips = _cache["ips"]
    if not fresh:
        with db_factory() as db:
            ips = frozenset(block.ip_address for block in db.scalars(active_blocks_query()).all())
        with _lock:
            _cache.update(loaded_at=now, ips=ips)
    return ip in ips


def find_active(db: Session, ip: str) -> IpBlock | None:
    return db.scalars(active_blocks_query().where(IpBlock.ip_address == ip).limit(1)).first()
