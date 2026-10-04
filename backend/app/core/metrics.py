"""In-process counters for the admin System page (reset when the server restarts)."""

import threading
import time
from collections import deque
from datetime import datetime, timezone

STARTED_AT = datetime.now(timezone.utc)
_started_monotonic = time.monotonic()
_lock = threading.Lock()
_counts = {"requests": 0, "server_errors": 0, "client_errors": 0}
# Last application errors: type and path only – never request bodies or messages with data.
recent_errors: deque = deque(maxlen=50)


def uptime_seconds() -> int:
    return int(time.monotonic() - _started_monotonic)


def record_request(status_code: int) -> None:
    with _lock:
        _counts["requests"] += 1
        if status_code >= 500:
            _counts["server_errors"] += 1
        elif status_code >= 400:
            _counts["client_errors"] += 1


def record_error(method: str, path: str, error: Exception) -> None:
    with _lock:
        recent_errors.appendleft(
            {"at": datetime.now(timezone.utc).isoformat(), "method": method, "path": path, "error": type(error).__name__}
        )


def snapshot() -> dict:
    with _lock:
        requests = _counts["requests"]
        return {
            **_counts,
            "error_rate": round(_counts["server_errors"] / requests, 4) if requests else 0.0,
            "recent_errors": list(recent_errors),
        }
