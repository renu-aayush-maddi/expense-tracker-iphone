"""Find the real client IP address – without trusting spoofable headers.

On Render, Cloudflare sits in front of the app and Render's proxy APPENDS to
X-Forwarded-For ("<client>, <cloudflare edge>"), so neither end of that header
is safe to use. Cloudflare overwrites True-Client-IP / CF-Connecting-IP on every
request, so those are configured via CLIENT_IP_HEADERS in production.

Locally (CLIENT_IP_HEADERS empty) the direct socket address is used, so a
client can never fake its IP by sending headers.
"""

import ipaddress

from starlette.requests import HTTPConnection

from app.core.config import settings


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def get_client_ip(request: HTTPConnection) -> str:
    for header in settings.client_ip_headers_list:
        ip = _valid_ip(request.headers.get(header))
        if ip:
            return ip
    if request.client and request.client.host:
        return _valid_ip(request.client.host) or request.client.host
    return "unknown"


def get_user_agent(request: HTTPConnection) -> str | None:
    agent = request.headers.get("user-agent")
    return agent[:300] if agent else None


def describe_user_agent(agent: str | None) -> str:
    """'Mozilla/5.0 (iPhone; ...) Safari' -> 'Safari on iPhone' (best effort, for display only)."""
    if not agent:
        return "Unknown device"
    a = agent.lower()
    if "shortcuts" in a or a.startswith("cfnetwork") or ("darwin" in a and "mozilla" not in a):
        return "iPhone Shortcut"
    device = next(
        (name for key, name in [("iphone", "iPhone"), ("ipad", "iPad"), ("android", "Android"),
                                ("windows", "Windows"), ("mac os", "macOS"), ("linux", "Linux")] if key in a),
        "Unknown OS",
    )
    browser = next(
        (name for key, name in [("edg/", "Edge"), ("chrome/", "Chrome"), ("firefox/", "Firefox"),
                                ("safari/", "Safari"), ("python", "Script"), ("curl", "curl")] if key in a),
        "Browser",
    )
    return f"{browser} on {device}"
