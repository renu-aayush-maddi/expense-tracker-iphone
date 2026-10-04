"""Admin: dashboard overview, system health and reports."""

import os
import platform
import time
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.admin.logs import csv_response
from app.api.deps import require_permission
from app.core import metrics
from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.permissions import Permission
from app.core.security import create_access_token, decode_access_token
from app.core.timeutils import today_local
from app.db.session import get_db
from app.models import User
from app.services import admin_stats, audit_service, ip_block_service, llm_extractor
from app.services.admin_service import resolve_range
from app.services.phonepe_parser import parse_phonepe_receipt

router = APIRouter(tags=["admin: overview"])

RangeKey = Literal["today", "7d", "30d", "90d", "custom"]


@router.get("/dashboard")
def dashboard(
    range_key: RangeKey = Query(default="30d", alias="range"),
    start: date | None = None,
    end: date | None = None,
    admin: User = Depends(require_permission(Permission.DASHBOARD_VIEW)),
    db: Session = Depends(get_db),
):
    range_start, range_end = resolve_range(range_key, start, end, today_local())
    data = admin_stats.dashboard(db, range_start, range_end)
    data["system"] = _health(db, brief=True)
    return data


# ---------------------------------------------------------------- system health
_SAMPLE_RECEIPT = "Paid to\nTest Merchant\nAmount:\n₹100\nDate:\n1 October 2026\nTransaction ID:\nT2610011200000000000001\nUTR:\n700000000001"


def _check(fn) -> dict:
    started = time.perf_counter()
    try:
        detail = fn()
        return {"status": "healthy", "latency_ms": round((time.perf_counter() - started) * 1000, 1), "detail": detail}
    except Exception as error:  # report the failure type only, never internals/secrets
        return {"status": "unhealthy", "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "detail": type(error).__name__}


def _health(db: Session, brief: bool = False) -> dict:
    def database():
        db.execute(text("SELECT 1"))
        return "connected"

    def authentication():
        claims = decode_access_token(create_access_token("health-check", "health-check"))
        if not claims:
            raise RuntimeError("token round-trip failed")
        return "token signing ok"

    def parser():
        result = parse_phonepe_receipt(_SAMPLE_RECEIPT)
        if str(result.data.amount) != "100.00":
            raise RuntimeError("unexpected parse")
        return "sample receipt parsed"

    components = {"api": {"status": "healthy", "latency_ms": 0, "detail": "responding"},
                  "database": _check(database), "authentication": _check(authentication),
                  "phonepe_import": _check(parser)}
    overall = "healthy" if all(c["status"] == "healthy" for c in components.values()) else "degraded"
    data = {"status": overall, "components": components, "uptime_seconds": metrics.uptime_seconds()}
    if not brief:
        snapshot = metrics.snapshot()
        data.update(
            environment=settings.ENVIRONMENT,
            version=settings.APP_VERSION,
            build=(os.environ.get("RENDER_GIT_COMMIT") or "local")[:7],  # Render sets this; not a secret
            python=platform.python_version(),
            started_at=metrics.STARTED_AT.isoformat(),
            ai_fallback="enabled" if llm_extractor.is_enabled() else "disabled",  # never the key itself
            requests=snapshot["requests"],
            server_errors=snapshot["server_errors"],
            client_errors=snapshot["client_errors"],
            error_rate=snapshot["error_rate"],
            recent_errors=snapshot["recent_errors"],
        )
    else:
        data["recent_errors"] = len(metrics.recent_errors)
    return data


@router.get("/system/health")
def system_health(request: Request, admin: User = Depends(require_permission(Permission.SYSTEM_VIEW)),
                  db: Session = Depends(get_db)):
    data = _health(db)
    data["blocked_ips"] = len(db.scalars(ip_block_service.active_blocks_query()).all())
    # Helps verify IP detection after deploying behind a proxy (shows only YOUR own request).
    data["your_request"] = {
        "detected_ip": get_client_ip(request),
        "ip_source": next((h for h in settings.client_ip_headers_list if request.headers.get(h)), "connection address"),
        "x_forwarded_for_entries": len([p for p in (request.headers.get("x-forwarded-for") or "").split(",") if p.strip()]),
    }
    return data


# ---------------------------------------------------------------- reports
REPORTS = {
    "users": admin_stats.users_report,
    "transactions": admin_stats.transactions_report,
    "security": admin_stats.security_report,
}


@router.get("/reports/{report}")
def report(
    report: Literal["users", "transactions", "security"],
    range_key: RangeKey = Query(default="30d", alias="range"),
    start: date | None = None,
    end: date | None = None,
    admin: User = Depends(require_permission(Permission.REPORTS_VIEW)),
    db: Session = Depends(get_db),
):
    range_start, range_end = resolve_range(range_key, start, end, today_local())
    return {"start": range_start, "end": range_end, **REPORTS[report](db, range_start, range_end)}


@router.get("/reports/{report}/export.csv")
def export_report(
    report: Literal["users", "transactions", "security"],
    request: Request,
    range_key: RangeKey = Query(default="30d", alias="range"),
    start: date | None = None,
    end: date | None = None,
    admin: User = Depends(require_permission(Permission.DATA_EXPORT)),
    db: Session = Depends(get_db),
):
    """Aggregated report as CSV (no passwords, tokens or raw receipts). Every export is audited."""
    range_start, range_end = resolve_range(range_key, start, end, today_local())
    data = REPORTS[report](db, range_start, range_end)
    rows: list[list] = [["Report", report], ["From", range_start.isoformat()], ["To", range_end.isoformat()], []]
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            rows.append([])
            rows.append([key] + list(value[0].keys()))
            rows.extend([[""] + list(item.values()) for item in value])
        elif isinstance(value, dict):
            rows.append([])
            rows.append([key])
            rows.extend([["", k, v] for k, v in value.items()])
        else:
            rows.append([key, value])
    audit_service.record(db, "REPORT_EXPORTED", actor=admin, request=request, resource_type="report", resource_id=report,
                         details={"start": range_start.isoformat(), "end": range_end.isoformat()})
    return csv_response(f"{report}-report-{range_start}-{range_end}.csv", ["Field", "Value"], rows)
