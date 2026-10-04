import logging
import time

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import metrics
from app.core.client_ip import get_client_ip

logger = logging.getLogger("app")

# Paths a blocked IP may still reach (Render's health check must keep working).
IP_BLOCK_EXEMPT = {"/api/health", "/"}


class BodySizeLimitMiddleware:
    """Reject request bodies larger than `max_bytes` with 413.

    Checks the Content-Length header up front, and also counts the bytes
    actually received (for requests without that header).
    """

    def __init__(self, app: ASGIApp, max_bytes: int, path_limits: dict[str, int] | None = None):
        self.app = app
        self.max_bytes = max_bytes
        # Larger limits for specific routes (e.g. receipt image uploads).
        self.path_limits = path_limits or {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        max_bytes = self.max_bytes
        if headers.get(b"content-type", b"").lower().startswith(b"multipart/form-data"):
            max_bytes = self.path_limits.get(scope["path"], self.max_bytes)  # only file uploads get the bigger limit
        content_length = headers.get(b"content-length")
        if content_length and content_length.isdigit() and int(content_length) > max_bytes:
            await _send_json(send, 413, b'{"detail":"Request is too large."}')
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Request is too large.")
            return message

        await self.app(scope, limited_receive, send)


class IpBlockMiddleware:
    """Reject API requests from admin-blocked IPs (403) and record them (throttled)."""

    def __init__(self, app: ASGIApp, session_factory):
        self.app = app
        self.session_factory = session_factory
        self._last_logged: dict[str, float] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in IP_BLOCK_EXEMPT or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        from app.services import ip_block_service, security_service  # avoid import cycles at startup

        ip = get_client_ip(HTTPConnection(scope))
        try:
            blocked = ip_block_service.is_blocked(self.session_factory, ip)
        except Exception:  # never take the whole API down because the blocklist can't be read
            logger.exception("IP blocklist check failed")
            blocked = False
        if not blocked:
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        if len(self._last_logged) > 10_000:  # keep memory bounded under a flood of IPs
            self._last_logged.clear()
        if now - self._last_logged.get(ip, 0) > 60:  # at most one DB record per IP per minute
            self._last_logged[ip] = now
            try:
                with self.session_factory() as db:
                    security_service.record_event(
                        db, security_service.BLOCKED_IP_REQUEST, ip=ip, success=False, severity="warning",
                        reason=f"{scope['method']} {scope['path']}",
                    )
                    security_service.after_blocked_request(db, ip)
            except Exception:
                logger.exception("Could not record blocked request")
        await _send_json(send, 403, b'{"detail":"Access from your network has been blocked."}')


class RequestMetricsMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status_holder = {"code": 500}

        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            metrics.record_request(status_holder["code"])


async def _send_json(send: Send, status_code: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
