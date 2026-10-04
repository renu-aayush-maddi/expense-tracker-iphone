"""Admin system: authorization, user management, sessions, IP blocking, audit."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AuditLog, SecurityEvent, Transaction, UserSession
from tests.conftest import SAMPLE_OCR, make_user, user_id

PASSWORD = "supersecret123"


@pytest.fixture
def super_admin(client):
    return make_user(client, "root@example.com", "super_admin")


@pytest.fixture
def admin(client):
    return make_user(client, "admin@example.com", "admin")


@pytest.fixture
def read_only(client):
    return make_user(client, "viewer@example.com", "read_only_admin")


@pytest.fixture
def victim(client):
    headers = make_user(client, "alice@example.com")
    client.post("/api/transactions", json={"amount": "250", "merchant_name": "Uber", "transaction_date": "2026-10-01",
                                           "utr": "123456789012"}, headers=headers)
    return {"headers": headers, "id": user_id(client, headers)}


def audit_actions(**filters):
    with SessionLocal() as db:
        query = select(AuditLog)
        for key, value in filters.items():
            query = query.where(getattr(AuditLog, key) == value)
        return [a.action for a in db.scalars(query).all()]


def last_audit(action):
    with SessionLocal() as db:
        return db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at.desc())).first()


# ================================================================ authorization
ADMIN_GETS = [
    "/api/admin/dashboard", "/api/admin/users", "/api/admin/transactions", "/api/admin/audit-logs",
    "/api/admin/security-events", "/api/admin/sessions", "/api/admin/ip-addresses", "/api/admin/ip-blocks",
    "/api/admin/system/health", "/api/admin/reports/users", "/api/admin/reports/transactions",
    "/api/admin/reports/security", "/api/admin/admins",
]


def test_normal_user_cannot_access_any_admin_api(client, victim):
    for path in ADMIN_GETS:
        assert client.get(path, headers=victim["headers"]).status_code == 403, path
    for path in [f"/api/admin/users/{victim['id']}/block", f"/api/admin/users/{victim['id']}/role", "/api/admin/ip-blocks"]:
        assert client.post(path, json={"reason": "x" * 5, "role": "super_admin", "password": PASSWORD,
                                       "ip_address": "1.2.3.4"}, headers=victim["headers"]).status_code == 403, path
    with SessionLocal() as db:  # attempts are recorded
        assert db.scalar(select(SecurityEvent).where(SecurityEvent.event_type == "admin_access_denied")) is not None


def test_unauthenticated_gets_401(client):
    for path in ADMIN_GETS:
        assert client.get(path).status_code == 401, path


def test_read_only_admin_can_view_but_not_change(client, read_only, victim):
    for path in ADMIN_GETS:
        expected = 403 if path == "/api/admin/admins" else 200
        assert client.get(path, headers=read_only).status_code == expected, path
    uid = victim["id"]
    assert client.post(f"/api/admin/users/{uid}/block", json={"reason": "spam"}, headers=read_only).status_code == 403
    assert client.post(f"/api/admin/users/{uid}/force-logout", json={}, headers=read_only).status_code == 403
    assert client.post(f"/api/admin/users/{uid}/reset-password", json={"password": PASSWORD}, headers=read_only).status_code == 403
    assert client.patch(f"/api/admin/users/{uid}", json={"full_name": "X"}, headers=read_only).status_code == 403
    assert client.post("/api/admin/ip-blocks", json={"ip_address": "1.2.3.4", "reason": "bad"}, headers=read_only).status_code == 403
    assert client.get("/api/admin/reports/users/export.csv", headers=read_only).status_code == 403
    assert client.get("/api/admin/audit-logs/export.csv", headers=read_only).status_code == 403


def test_admin_cannot_manage_roles_or_other_admins(client, admin, read_only):
    other_admin = user_id(client, read_only)
    assert client.post(f"/api/admin/users/{other_admin}/block", json={"reason": "nope"}, headers=admin).status_code == 403
    assert client.post(f"/api/admin/users/{other_admin}/role", json={"role": "user", "password": PASSWORD},
                       headers=admin).status_code == 403
    assert client.get("/api/admin/admins", headers=admin).status_code == 403


def test_user_cannot_escalate_via_register_or_profile(client, admin, victim):
    response = client.post("/api/auth/register", json={"email": "evil@example.com", "password": PASSWORD, "role": "super_admin"})
    assert response.status_code == 422  # unknown field rejected
    response = client.patch(f"/api/admin/users/{victim['id']}", json={"role": "super_admin"}, headers=admin)
    assert response.status_code == 422  # mass assignment rejected
    response = client.patch(f"/api/admin/users/{victim['id']}", json={"status": "active"}, headers=admin)
    assert response.status_code == 422


def test_nobody_acts_on_themselves(client, super_admin):
    me = user_id(client, super_admin)
    assert client.post(f"/api/admin/users/{me}/role", json={"role": "user", "password": PASSWORD},
                       headers=super_admin).status_code == 403
    assert client.post(f"/api/admin/users/{me}/block", json={"reason": "oops"}, headers=super_admin).status_code == 403


def test_super_admin_role_changes(client, super_admin, victim):
    uid = victim["id"]
    bad = client.post(f"/api/admin/users/{uid}/role", json={"role": "admin", "password": "wrong"}, headers=super_admin)
    assert bad.status_code == 403  # re-authentication required
    ok = client.post(f"/api/admin/users/{uid}/role", json={"role": "admin", "password": PASSWORD, "reason": "helper"},
                     headers=super_admin)
    assert ok.status_code == 200 and ok.json()["role"] == "admin"
    # The promoted user's old session ended (new privileges = new login).
    assert client.get("/api/auth/me", headers=victim["headers"]).status_code == 401
    entry = last_audit("USER_ROLE_CHANGED")
    assert entry.details["from"] == "user" and entry.details["to"] == "admin" and entry.actor_email == "root@example.com"
    with SessionLocal() as db:
        assert db.scalar(select(SecurityEvent).where(SecurityEvent.event_type == "reauth_failed")) is not None


def test_add_admin_and_list(client, super_admin, victim):
    response = client.post("/api/admin/admins", json={"email": "alice@example.com", "role": "read_only_admin",
                                                      "password": PASSWORD}, headers=super_admin)
    assert response.status_code == 201
    emails = [a["email"] for a in client.get("/api/admin/admins", headers=super_admin).json()["items"]]
    assert set(emails) == {"root@example.com", "alice@example.com"}


def test_last_super_admin_protection(client, super_admin):
    from app.api.admin.common import get_target_user  # noqa: F401  (exercise via service)
    from app.services import admin_service

    with SessionLocal() as db:
        from app.models import User

        root = db.scalar(select(User).where(User.email == "root@example.com"))
        with pytest.raises(Exception) as error:
            admin_service.ensure_other_super_admin(db, root)
        assert "at least one active super admin" in str(error.value.detail)


# ================================================================ user management
def test_block_user_flow(client, admin, victim):
    uid = victim["id"]
    assert client.post(f"/api/admin/users/{uid}/block", json={"reason": ""}, headers=admin).status_code == 422
    response = client.post(f"/api/admin/users/{uid}/block", json={"reason": "Suspicious login activity"}, headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["status_reason"] == "Suspicious login activity"
    assert body["status_changed_by_email"] == "admin@example.com"
    assert body["active_sessions"] == 0

    # Existing session no longer works, login is refused, data is intact.
    assert client.get("/api/transactions", headers=victim["headers"]).status_code == 401
    login = client.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert login.status_code == 403 and "blocked" in login.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(Transaction).where(Transaction.merchant_name == "Uber")) is not None

    entry = last_audit("USER_BLOCKED")
    assert entry.target_email == "alice@example.com"
    assert entry.details["reason"] == "Suspicious login activity" and entry.details["sessions_revoked"] >= 1

    assert client.post(f"/api/admin/users/{uid}/unblock", json={}, headers=admin).json()["status"] == "active"
    assert client.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 200
    assert "USER_UNBLOCKED" in audit_actions()


def test_blocked_user_import_token_rejected(client, admin, victim):
    token = client.post("/api/settings/tokens", json={"name": "phone"}, headers=victim["headers"]).json()["token"]
    client.post(f"/api/admin/users/{victim['id']}/block", json={"reason": "abuse"}, headers=admin)
    response = client.post("/api/transactions/import/phonepe", json={"ocr_text": SAMPLE_OCR},
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_disable_enable_suspend(client, admin, victim):
    uid = victim["id"]
    assert client.post(f"/api/admin/users/{uid}/disable", json={"reason": "user request"}, headers=admin).json()["status"] == "disabled"
    assert client.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 403
    assert client.post(f"/api/admin/users/{uid}/enable", json={}, headers=admin).json()["status"] == "active"
    assert client.post(f"/api/admin/users/{uid}/suspend", json={"reason": "chargeback"}, headers=admin).json()["status"] == "suspended"
    assert {"USER_DISABLED", "USER_ENABLED", "USER_SUSPENDED"} <= set(audit_actions())


def test_force_logout(client, admin, victim):
    # The helper registers (1 session) and logs in (another), so the user has 2 sessions.
    response = client.post(f"/api/admin/users/{victim['id']}/force-logout", json={"reason": "lost phone"}, headers=admin)
    assert response.json()["sessions_revoked"] == 2
    assert client.get("/api/auth/me", headers=victim["headers"]).status_code == 401
    assert last_audit("USER_FORCE_LOGOUT").details["sessions_revoked"] == 2


def test_reset_password_flow(client, admin, victim):
    uid = victim["id"]
    response = client.post(f"/api/admin/users/{uid}/reset-password", json={"password": PASSWORD}, headers=admin)
    assert response.status_code == 200
    temporary = response.json()["temporary_password"]
    assert client.get("/api/auth/me", headers=victim["headers"]).status_code == 401  # sessions revoked
    assert client.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 401

    token = client.post("/api/auth/login", json={"email": "alice@example.com", "password": temporary}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).json()["must_change_password"] is True
    blocked = client.get("/api/transactions", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "password_change_required"

    changed = client.post("/api/auth/change-password", json={"current_password": temporary, "new_password": "brand-new-pass-1"},
                          headers=headers)
    assert changed.status_code == 204
    assert client.get("/api/transactions", headers=headers).status_code == 200
    entry = last_audit("PASSWORD_RESET_BY_ADMIN")
    assert "password" not in str(entry.details).lower().replace("password_reset", "")
    assert temporary not in str(entry.details)


def test_delete_requires_super_admin_and_is_soft(client, admin, super_admin, victim):
    uid = victim["id"]
    assert client.post(f"/api/admin/users/{uid}/delete", json={"password": PASSWORD}, headers=admin).status_code == 403
    response = client.post(f"/api/admin/users/{uid}/delete", json={"password": PASSWORD, "reason": "GDPR request"},
                           headers=super_admin)
    assert response.status_code == 200 and response.json()["status"] == "deleted"
    assert client.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 403
    assert uid not in [u["id"] for u in client.get("/api/admin/users", headers=super_admin).json()["items"]]
    with SessionLocal() as db:
        assert db.scalar(select(Transaction).where(Transaction.merchant_name == "Uber")) is not None  # data kept
    restored = client.post(f"/api/admin/users/{uid}/restore", json={"password": PASSWORD}, headers=super_admin)
    assert restored.json()["status"] == "active"


def test_user_list_filters_and_aggregates(client, admin, victim):
    make_user(client, "bob@example.com")
    data = client.get("/api/admin/users?q=alice", headers=admin).json()
    assert data["total"] == 1
    row = data["items"][0]
    assert row["transaction_count"] == 1 and row["transaction_total"] == "250.00" and row["active_sessions"] == 2
    assert row["registration_ip"] == "testclient"
    sorted_rows = client.get("/api/admin/users?sort_by=transactions&sort_order=desc&page_size=1", headers=admin).json()
    assert sorted_rows["items"][0]["email"] == "alice@example.com" and sorted_rows["pages"] >= 3
    assert client.get("/api/admin/users?status=blocked", headers=admin).json()["total"] == 0
    assert "password" not in str(data).replace("must_change_password", "")


def test_user_detail_activity_security_finance(client, admin, victim):
    uid = victim["id"]
    assert client.get(f"/api/admin/users/{uid}", headers=admin).status_code == 200
    assert "USER_VIEWED" in audit_actions()
    timeline = client.get(f"/api/admin/users/{uid}/activity", headers=admin).json()
    kinds = {item["kind"] for item in timeline}
    assert {"security", "transaction", "admin"} <= kinds
    security = client.get(f"/api/admin/users/{uid}/security", headers=admin).json()
    assert security["known_ips"][0]["ip_address"] == "testclient"
    assert all("token" not in s for s in security["sessions"])
    finance = client.get(f"/api/admin/users/{uid}/finance", headers=admin).json()
    assert finance["total_spending"] == "250.00"
    assert finance["recent_transactions"][0]["utr_masked"] == "••••9012"


# ================================================================ sessions
def test_logout_revokes_session(client, victim):
    assert client.post("/api/auth/logout", headers=victim["headers"]).status_code == 204
    assert client.get("/api/auth/me", headers=victim["headers"]).status_code == 401


def test_admin_sessions_list_and_revoke(client, admin, victim):
    sessions = client.get(f"/api/admin/sessions?user_id={victim['id']}", headers=admin).json()["items"]
    assert len(sessions) == 2  # registration + login
    assert set(sessions[0]) >= {"device", "ip_address", "status"} and "token" not in str(sessions[0]).lower()
    for session in sessions:
        client.post(f"/api/admin/sessions/{session['id']}/revoke", json={"reason": "suspicious"}, headers=admin)
    assert client.get("/api/auth/me", headers=victim["headers"]).status_code == 401
    remaining = client.get(f"/api/admin/sessions?user_id={victim['id']}", headers=admin).json()["items"]
    assert remaining == []
    assert "SESSION_REVOKED" in audit_actions()


def test_admin_idle_timeout(client, admin):
    with SessionLocal() as db:
        for session in db.scalars(select(UserSession)).all():
            session.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=settings.ADMIN_IDLE_TIMEOUT_MINUTES + 5)
        db.commit()
    assert client.get("/api/admin/dashboard", headers=admin).status_code == 401


def test_tokens_without_session_are_rejected(client, victim):
    import jwt

    old_style = jwt.encode({"sub": victim["id"], "type": "access", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                           settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_style}"}).status_code == 401


def test_change_password_logs_out_other_devices(client):
    first = make_user(client, "carol@example.com")
    second = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "carol@example.com",
                                                                              "password": PASSWORD}).json()["access_token"]}
    assert client.post("/api/auth/change-password", json={"current_password": "wrong", "new_password": "another-pass-9"},
                       headers=first).status_code == 400
    assert client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "another-pass-9"},
                       headers=first).status_code == 204
    assert client.get("/api/auth/me", headers=first).status_code == 200
    assert client.get("/api/auth/me", headers=second).status_code == 401


# ================================================================ brute force & suspicious activity
def test_account_lockout(client, monkeypatch):
    from app.api.auth import login_limiter

    monkeypatch.setattr(login_limiter, "max_requests", 100)
    make_user(client, "dave@example.com")
    for _ in range(settings.LOCKOUT_THRESHOLD):
        assert client.post("/api/auth/login", json={"email": "dave@example.com", "password": "wrong-pass"}).status_code == 401
    locked = client.post("/api/auth/login", json={"email": "dave@example.com", "password": PASSWORD})
    assert locked.status_code == 429  # even the right password is refused while locked
    with SessionLocal() as db:
        types = set(db.scalars(select(SecurityEvent.event_type)).all())
    assert {"account_locked", "suspicious_failed_logins", "login_blocked"} <= types


def test_credential_stuffing_detected(client, monkeypatch):
    from app.api.auth import login_limiter

    monkeypatch.setattr(login_limiter, "max_requests", 100)
    for i in range(3):
        client.post("/api/auth/login", json={"email": f"nobody{i}@example.com", "password": "guess-123"})
    with SessionLocal() as db:
        event = db.scalar(select(SecurityEvent).where(SecurityEvent.event_type == "suspicious_credential_stuffing"))
    assert event is not None and event.severity == "critical"


def test_admin_login_attempts_are_audited(client, admin):
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong-pass"})
    actions = audit_actions(actor_email="admin@example.com")
    assert "ADMIN_LOGIN" in actions and "ADMIN_LOGIN_FAILED" in actions


# ================================================================ IP detection & blocking
@pytest.fixture
def cf_header(monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_IP_HEADERS", "cf-connecting-ip")
    return lambda ip: {"cf-connecting-ip": ip}


def test_ip_block_flow(client, admin, cf_header):
    admin_ip = cf_header("198.51.100.1")
    headers = {**admin, **admin_ip}
    attacker = cf_header("203.0.113.66")
    make_user(client, "erin@example.com")

    assert client.post("/api/admin/ip-blocks", json={"ip_address": "not-an-ip", "reason": "bad"}, headers=headers).status_code == 422
    assert client.post("/api/admin/ip-blocks", json={"ip_address": "198.51.100.1", "reason": "self"},
                       headers=headers).status_code == 409  # can't lock yourself out
    block = client.post("/api/admin/ip-blocks", json={"ip_address": "203.0.113.66", "reason": "credential stuffing"},
                        headers=headers)
    assert block.status_code == 201 and block.json()["blocked_by_email"] == "admin@example.com"

    login = client.post("/api/auth/login", json={"email": "erin@example.com", "password": PASSWORD}, headers=attacker)
    assert login.status_code == 403
    assert client.get("/api/health", headers=attacker).status_code == 200  # health check stays reachable
    # A forged X-Forwarded-For can't bypass the block (the trusted header wins).
    spoofed = {**attacker, "x-forwarded-for": "8.8.8.8"}
    assert client.post("/api/auth/login", json={"email": "erin@example.com", "password": PASSWORD}, headers=spoofed).status_code == 403
    # Other IPs are unaffected.
    assert client.post("/api/auth/login", json={"email": "erin@example.com", "password": PASSWORD},
                       headers=cf_header("192.0.2.10")).status_code == 200

    with SessionLocal() as db:
        assert db.scalar(select(SecurityEvent).where(SecurityEvent.event_type == "blocked_ip_request")) is not None
    detail = client.get("/api/admin/ip-addresses/203.0.113.66", headers=headers).json()
    assert detail["blocked"] is True

    client.post(f"/api/admin/ip-blocks/{block.json()['id']}/unblock", json={"reason": "false positive"}, headers=headers)
    assert client.post("/api/auth/login", json={"email": "erin@example.com", "password": PASSWORD}, headers=attacker).status_code == 200
    assert {"IP_BLOCKED", "IP_UNBLOCKED"} <= set(audit_actions())


def test_ip_addresses_aggregate(client, admin, victim):
    rows = client.get("/api/admin/ip-addresses", headers=admin).json()["items"]
    row = next(r for r in rows if r["ip_address"] == "testclient")
    assert row["users"] >= 2 and row["successful_logins"] >= 2


def test_x_forwarded_for_is_ignored_without_trusted_header(client, victim):
    from app.core.client_ip import get_client_ip
    from starlette.requests import Request

    request = Request({"type": "http", "headers": [(b"x-forwarded-for", b"6.6.6.6")], "client": ("10.0.0.5", 1234)})
    assert get_client_ip(request) == "10.0.0.5"


# ================================================================ audit log integrity
def test_audit_log_is_append_only(client, admin, victim):
    client.post(f"/api/admin/users/{victim['id']}/force-logout", json={}, headers=admin)
    with SessionLocal() as db:
        entry = db.scalars(select(AuditLog)).first()
        entry.action = "TAMPERED"
        with pytest.raises(PermissionError):
            db.commit()
        db.rollback()
        entry = db.scalars(select(AuditLog)).first()
        db.delete(entry)
        with pytest.raises(PermissionError):
            db.commit()
    entry_id = last_audit("USER_FORCE_LOGOUT").id
    assert client.put(f"/api/admin/audit-logs/{entry_id}", json={}, headers=admin).status_code == 405
    assert client.delete(f"/api/admin/audit-logs/{entry_id}", headers=admin).status_code == 405


def test_audit_log_listing_filter_detail_and_export(client, admin, victim):
    client.post(f"/api/admin/users/{victim['id']}/block", json={"reason": "spam"}, headers=admin)
    page = client.get("/api/admin/audit-logs?action=USER_BLOCKED", headers=admin).json()
    assert page["total"] == 1 and page["items"][0]["details"]["reason"] == "spam"
    detail = client.get(f"/api/admin/audit-logs/{page['items'][0]['id']}", headers=admin).json()
    assert detail["target_email"] == "alice@example.com"
    export = client.get("/api/admin/audit-logs/export.csv?action=USER_BLOCKED", headers=admin)
    assert export.status_code == 200 and "USER_BLOCKED" in export.text
    assert "AUDIT_LOG_EXPORTED" in audit_actions()


# ================================================================ transactions administration
def test_admin_transaction_soft_delete(client, admin, victim):
    rows = client.get("/api/admin/transactions?user=alice", headers=admin).json()["items"]
    tid = rows[0]["id"]
    detail = client.get(f"/api/admin/transactions/{tid}", headers=admin).json()
    assert detail["utr_masked"] == "••••9012" and "raw_ocr_text" not in detail and "notes" not in detail
    assert "TRANSACTION_VIEWED" in audit_actions()

    assert client.post(f"/api/admin/transactions/{tid}/delete", json={"reason": "duplicate import"}, headers=admin).status_code == 200
    assert client.get("/api/transactions", headers=victim["headers"]).json()["total"] == 0  # hidden from the user
    assert client.get(f"/api/transactions/{tid}", headers=victim["headers"]).status_code == 404
    stats = client.get("/api/stats/dashboard?year=2026&month=10", headers=victim["headers"]).json()
    assert stats["month_total"] == "0.00"
    with SessionLocal() as db:
        assert db.get(Transaction, __import__("uuid").UUID(tid)) is not None  # still in the database
    entry = last_audit("TRANSACTION_DELETED")
    assert entry.target_email == "alice@example.com" and entry.details["reason"] == "duplicate import"

    assert client.get("/api/admin/transactions?deleted=only", headers=admin).json()["total"] == 1
    client.post(f"/api/admin/transactions/{tid}/restore", json={"reason": "mistake"}, headers=admin)
    assert client.get("/api/transactions", headers=victim["headers"]).json()["total"] == 1


# ================================================================ dashboard, system, reports
def test_dashboard_and_reports(client, admin, victim):
    data = client.get("/api/admin/dashboard?range=7d", headers=admin).json()
    assert data["users"]["total"] >= 2 and data["transactions"]["total"] == 1
    assert len(data["series"]["registrations"]) == 7
    assert data["system"]["components"]["database"]["status"] == "healthy"
    custom = client.get("/api/admin/dashboard?range=custom&start=2026-09-01&end=2026-09-30", headers=admin)
    assert custom.status_code == 200 and len(custom.json()["series"]["transactions"]) == 30
    assert client.get("/api/admin/dashboard?range=custom", headers=admin).status_code == 422
    for report in ("users", "transactions", "security"):
        assert client.get(f"/api/admin/reports/{report}?range=30d", headers=admin).status_code == 200
    export = client.get("/api/admin/reports/transactions/export.csv?range=90d", headers=admin)
    assert export.status_code == 200 and "transaction_count" in export.text
    assert last_audit("REPORT_EXPORTED").resource_id == "transactions"


def test_system_health_exposes_no_secrets(client, admin):
    response = client.get("/api/admin/system/health", headers=admin)
    assert response.status_code == 200
    text = response.text
    assert settings.JWT_SECRET not in text
    assert "DATABASE_URL" not in text and "sqlite" not in text.lower()
    body = response.json()
    assert body["components"]["authentication"]["status"] == "healthy"
    assert body["your_request"]["detected_ip"] == "testclient"


# ================================================================ bootstrap & CLI
def test_initial_super_admin_bootstrap(client, monkeypatch):
    from app.services import admin_bootstrap

    make_user(client, "first@example.com")
    monkeypatch.setattr(settings, "INITIAL_SUPER_ADMIN_EMAIL", "first@example.com")
    assert admin_bootstrap.promote_initial_super_admin(SessionLocal) is True
    make_user(client, "second@example.com")
    monkeypatch.setattr(settings, "INITIAL_SUPER_ADMIN_EMAIL", "second@example.com")
    assert admin_bootstrap.promote_initial_super_admin(SessionLocal) is False  # a super admin already exists
    assert "ADMIN_BOOTSTRAPPED" in audit_actions()


def test_cli_create_admin(client, monkeypatch):
    from app import cli

    monkeypatch.setenv("ADMIN_PASSWORD", "cli-admin-pass-1")
    assert cli.main(["create-admin", "--email", "cli@example.com", "--role", "admin"]) == 0
    login = client.post("/api/auth/login", json={"email": "cli@example.com", "password": "cli-admin-pass-1"})
    assert login.json()["user"]["role"] == "admin"
    assert "users:manage" in login.json()["user"]["permissions"]


def test_admin_cannot_delete_super_admins_transactions(client, admin, super_admin):
    client.post("/api/transactions", json={"amount": "10", "merchant_name": "Tea", "transaction_date": "2026-10-01"},
                headers=super_admin)
    tid = client.get("/api/admin/transactions?user=root", headers=admin).json()["items"][0]["id"]
    assert client.post(f"/api/admin/transactions/{tid}/delete", json={"reason": "test"}, headers=admin).status_code == 403


def test_denied_admin_access_is_logged_once_per_minute(client, victim):
    for _ in range(5):
        client.get("/api/admin/users", headers=victim["headers"])
    with SessionLocal() as db:
        events = db.scalars(select(SecurityEvent).where(SecurityEvent.event_type == "admin_access_denied")).all()
    assert len(events) == 1
