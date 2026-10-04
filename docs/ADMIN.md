# Admin console & administration

The admin console lives at **`/admin`** in the web app. It sits on top of the existing app: same login, same API, same database. Normal users never see it, and **every `/api/admin/*` request is authorized on the server**. The frontend only hides buttons.

Contents: [First admin](#1-create-the-first-admin) · [Roles](#2-roles--permissions) · [Sessions](#3-sessions--login-security) · [Blocking users](#4-user-status--blocking) · [IP tracking & blocking](#5-ip-tracking--blocking) · [Audit log](#6-audit-log) · [Security monitoring](#7-security-monitoring) · [Privacy](#8-privacy--least-privilege) · [API](#9-admin-api) · [Database](#10-database-changes) · [Deployment](#11-production-deployment) · [Security notes](#12-security-design-notes) · [Limitations](#13-known-limitations)

---

## 1. Create the first admin

No password is ever stored in code or config. Pick one option.

**Option A: CLI (local, or against production)**

```bash
cd backend && source .venv/bin/activate
python -m app.cli create-admin --email you@example.com --name "You"     # asks for a password (hidden)
python -m app.cli list-admins
```

- If the account already exists, the CLI offers to promote it, and optionally to set a new password.
- For production, run it on your machine pointed at Supabase. Render's free plan has no shell.

  ```bash
  DATABASE_URL='postgresql://postgres.xxx:PASS@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require' \
  JWT_SECRET='any-value-at-least-32-characters-long' \
  python -m app.cli create-admin --email you@example.com
  ```

- For automation, `ADMIN_PASSWORD` can supply the password instead of the prompt. Prefer the prompt.

**Option B: `INITIAL_SUPER_ADMIN_EMAIL` (no shell needed)**

1. Register your account normally in the app.
2. On Render, set `INITIAL_SUPER_ADMIN_EMAIL=you@example.com` and redeploy.
3. At startup, that existing account becomes super admin, **but only if no super admin exists yet**. After that the variable does nothing, so leave it or remove it.
4. Log in again: role changes end existing sessions. You'll see an **Admin** link in the top navigation.

Either way, the promotion is written to the audit log (`ADMIN_CREATED_CLI` / `ADMIN_BOOTSTRAPPED`).

Other CLI tools:

```bash
python -m app.cli unblock-ip 203.0.113.7               # if an IP block ever locks you out
python -m app.cli revoke-sessions --email someone@example.com
```

## 2. Roles & permissions

Roles are stored in `users.role`. What each role may do is defined in `backend/app/core/permissions.py`. To add a role later (for example "support"), add it there; the rest of the code checks permissions, not role names.

| Permission | read_only_admin | admin | super_admin |
|---|:-:|:-:|:-:|
| View dashboard, users, transactions, audit logs, security events, sessions, IPs, system, reports | ✓ | ✓ | ✓ |
| Manage users: edit profile, block/unblock, disable/enable, suspend, force logout, reset password | | ✓ | ✓ |
| Soft-delete / restore transactions | | ✓ | ✓ |
| Revoke sessions, block/unblock IPs | | ✓ | ✓ |
| CSV exports (reports, audit log) | | ✓ | ✓ |
| Delete / restore user accounts (soft delete) | | | ✓ |
| Manage admins and roles | | | ✓ |

Rules enforced on the server for every action:

- **Nobody can act on their own account** (no self-block, no self role change).
- **Admins and read-only admins can act only on plain users.** Only a super admin can manage, block or reset another admin.
- **Roles change only through `POST /api/admin/users/{id}/role` or `POST /api/admin/admins`.** Both require `admins:manage` and the admin's own password. Register and profile-edit requests reject unknown fields (`extra="forbid"`), so a `"role"` field can't be sneaked in.
- **There must always be at least one active super admin.**
- **A role change ends the target's sessions**, so the new limits (for example admin timeouts) apply on their next login.

## 3. Sessions & login security

The app keeps its existing **Bearer token** design but makes it **server-side**. Each token carries a session id, and every request checks the `user_sessions` row:

- **Logout** (`POST /api/auth/logout`) revokes the session. The token stops working immediately.
- **Changing your password** (`POST /api/auth/change-password`) logs out your *other* devices.
- **Admins** can revoke one session, all sessions of a user, or all sessions from one IP.
- **Admin sessions** last 12 hours (`ADMIN_SESSION_HOURS`) and expire after 60 idle minutes (`ADMIN_IDLE_TIMEOUT_MINUTES`). Normal users keep 7 days.
- **Every login creates a new session**, which prevents session fixation. No tokens or secrets are stored in the database.
- **Why not cookies:** the frontend and API are on different `onrender.com` subdomains. `onrender.com` is a public suffix, so cookies would be third-party and Safari would block them.

Brute-force protection:

- **Per IP:** 10 login attempts a minute (`LOGIN_RATE_LIMIT_PER_MINUTE`).
- **Per account:** after 5 wrong passwords (`LOCKOUT_THRESHOLD`), the account is locked for 15 minutes (`LOCKOUT_MINUTES`), even for the right password. This is intentionally temporary: a permanent lockout would let an attacker lock people out.
- **Re-authentication** for sensitive admin actions is limited to 5 attempts a minute, and failures are recorded.
- **Admin logins**, successful and failed, are written to both the security log and the audit log (`ADMIN_LOGIN`, `ADMIN_LOGIN_FAILED`).

**Admin password reset:** the admin re-enters *their own* password and gets a **one-time temporary password**, shown once. The user's sessions end. When the user logs in with it, the app forces a password change before anything else; the API refuses other calls with `password_change_required`. There is no email system, so the admin passes the temporary password on through a safe channel.

## 4. User status & blocking

| Status | Meaning | Can log in | Sessions | Import token |
|---|---|:-:|---|:-:|
| `active` | normal | ✓ | kept | ✓ |
| `suspended` | temporary hold | ✗ | revoked | ✗ |
| `disabled` | turned off (e.g. on request) | ✗ | revoked | ✗ |
| `blocked` | security/abuse block | ✗ | revoked | ✗ |
| `deleted` | soft-deleted by a super admin | ✗ | revoked | deleted |

- **Blocking** asks for a reason, revokes every session immediately and refuses login and API access, including the iPhone Shortcut token. The account's data stays intact.
- **Who did it is kept:** `status_reason`, `status_changed_by_email` and `status_changed_at` are stored and shown, for example *"Blocked by admin@example.com · 4 Oct 2026, 5:30 pm · Reason: Suspicious login activity"*. The audit log has the full history with before and after values.
- **Unblock and enable** set the status back to `active`.
- **Delete** is a soft delete: the user can't log in, the account is hidden from lists, import tokens are removed, and transactions stay. A super admin can **Restore** it.

High-risk actions all go through a confirmation dialog:

| Action | Confirmation required |
|---|---|
| Block, disable, suspend, transaction delete, IP block | A reason |
| Force logout, session revoke | Confirmation; reason optional |
| Reset password, change role, add admin, delete/restore user | The admin's **password** |
| Delete user | The password, plus typing `DELETE` |

## 5. IP tracking & blocking

**What's recorded:** IPs are recorded only alongside security-relevant events. That means logins (success, failure, blocked), logouts, registrations, password changes and resets, session creation, admin actions (in the audit log), PhonePe import requests, and requests from blocked IPs. `/admin/ip-addresses` aggregates these per IP: first and last seen, users, events, successful and failed logins, and blocked status. Click an IP to inspect it.

**Blocking:** an admin enters the IP and a reason, with an optional expiry. From then on, every API request from that IP gets **403**, including login. `/api/health` stays reachable so Render's health check keeps working. Blocked requests are recorded, at most one record per IP per minute.

Safeguards:

- You **can't block the IP you're using right now**.
- **Nothing is blocked automatically.** Suspicious patterns are only flagged.
- Blocks are exact single addresses, never ranges.
- If you ever lock yourself out, run `python -m app.cli unblock-ip <ip>`. Running servers pick it up within 30 seconds.

**Real client IP behind Render:**

- Render puts Cloudflare in front, and Render's proxy *appends* to `X-Forwarded-For`, so a client can forge the left-most entry. The app therefore **never trusts `X-Forwarded-For`**.
- It reads the headers named in `CLIENT_IP_HEADERS`. In production that's `true-client-ip,cf-connecting-ip`, which Cloudflare overwrites on every request.
- Locally the setting is empty, and the direct connection address is used.
- **Verify after deploying:** open **System health → "Your request"** and check that *Detected IP* matches your real public IP.

## 6. Audit log

`audit_logs` records every administrative and sensitive action:

- **Fields:** actor id, email and role, action, resource type and id, target user id and email, result, IP, user agent, details (JSON) and time.
- **Actions recorded:**

  ```
  USER_VIEWED · USER_UPDATED · USER_BLOCKED · USER_UNBLOCKED · USER_DISABLED · USER_ENABLED · USER_SUSPENDED
  USER_DELETED · USER_RESTORED · USER_ROLE_CHANGED · USER_FORCE_LOGOUT · PASSWORD_RESET_BY_ADMIN
  SESSION_REVOKED · SESSIONS_REVOKED_BY_IP · IP_BLOCKED · IP_UNBLOCKED
  TRANSACTION_VIEWED · TRANSACTION_DELETED · TRANSACTION_RESTORED
  ADMIN_LOGIN · ADMIN_LOGIN_FAILED · ADMIN_BOOTSTRAPPED · ADMIN_CREATED_CLI
  REPORT_EXPORTED · AUDIT_LOG_EXPORTED
  ```

How it stays trustworthy:

- **Append-only, enforced in three places.** There are no update or delete endpoints. The ORM refuses to update or delete audit rows. A **PostgreSQL trigger rejects `UPDATE` and `DELETE`** on the table.
- **No foreign keys:** changing or deleting a user never rewrites history, because the actor and target emails are copied at the time of the action.
- **No secrets:** keys such as `password` and `token` are redacted automatically. Temporary passwords are never logged.
- **Written in the same database transaction** as the action it describes, so a change can't succeed without its audit entry.
- **Admin-only:** normal users have no route to it, and read-only admins can view but not export.

**UI:** `/admin/audit-logs` offers search, filters (action, result, date range), sort order and pagination. Click a row for full details with formatted JSON. CSV export is available, and the export itself is audited.

## 7. Security monitoring

`/admin/security` shows authentication events (user, time, IP, device or browser, result, reason) with filters for user, IP, event type, result and date range. A second tab lists suspicious activity, which is flagged automatically and **never blocked automatically**:

| Event | Trigger |
|---|---|
| `account_locked`, `suspicious_failed_logins` | 5+ wrong passwords for one account |
| `suspicious_many_ips` | failed logins for one account from 3+ IPs within an hour |
| `suspicious_credential_stuffing` (critical) | failed logins for 3+ different accounts from one IP within an hour |
| `new_ip_login` | successful login from an IP never seen for that account |
| `suspicious_blocked_requests` | 20+ requests from a blocked IP within 10 minutes |
| `suspicious_registrations` | 3+ signups from one IP within 24 hours |

Each pattern is flagged at most once per window, so a single attack doesn't flood the list.

**Three separate log streams:**

| Stream | Where it goes | Contents |
|---|---|---|
| `app` | server log | application events and errors |
| `security` | server log + the `security_events` table | authentication events |
| `audit` | server log + the `audit_logs` table | admin actions |

None of them contain passwords, tokens, API keys or receipt text.

## 8. Privacy & least privilege

- **What admins see of financial data:** merchant, amount, date, category and source. UTRs and PhonePe IDs are **masked** (`••••9012`). **Notes and raw receipt text are never exposed to admins**, and opening a transaction is audited.
- **What's collected:** only what account security needs: IPs and user agents on security events, last login and activity, signup IP. No page tracking or behavioural analytics.
- **Never returned by any admin endpoint:** password hashes, tokens and secrets. The system page reports component health, not environment values.

## 9. Admin API

All endpoints are under `/api/admin`. They need a login token from an account with an admin role.

- **Responses:** 401 when not logged in, 403 when the role is missing, 422 for invalid input.
- **Lists** are paginated on the server (`page`, `page_size` ≤ 100–200) and return `{items, total, page, page_size, pages}`.

| Method & path | Permission | Purpose |
|---|---|---|
| `GET /dashboard?range=today\|7d\|30d\|90d\|custom&start&end` | dashboard:view | Overview cards and daily series |
| `GET /users` (`q, role, status, created_from/to, active_from/to, sort_by, sort_order`) | users:view | User list with aggregates |
| `GET /users/{id}` · `/activity` · `/security` | users:view | Profile (audited), timeline, IPs/sessions/events |
| `GET /users/{id}/finance` | transactions:view | Spending overview (masked) |
| `PATCH /users/{id}` `{full_name, email}` | users:manage | Edit profile (role/status rejected) |
| `POST /users/{id}/block\|disable\|suspend` `{reason}` | users:manage | Change status, revoke sessions |
| `POST /users/{id}/unblock\|enable` `{reason?}` | users:manage | Back to active |
| `POST /users/{id}/force-logout` `{reason?}` | users:manage | Revoke all sessions |
| `POST /users/{id}/reset-password` `{password}` | users:manage | Temporary password (shown once) |
| `POST /users/{id}/delete\|restore` `{password, reason?}` | users:delete | Soft delete / restore |
| `POST /users/{id}/role` `{role, password, reason?}` | admins:manage | Change role |
| `GET /admins` · `POST /admins` `{email, role, password}` · `GET /admins/{id}/activity` | admins:manage | Admin management |
| `GET /transactions` (`user_id, user, merchant, category, source, date_from/to, min/max_amount, deleted, sort_by`) | transactions:view | All transactions |
| `GET /transactions/{id}` | transactions:view | Detail (audited, masked) |
| `POST /transactions/{id}/delete\|restore` `{reason}` | transactions:manage | Soft delete / restore |
| `GET /audit-logs` · `/audit-logs/{id}` · `/audit-logs/actions` | audit:view | Audit log |
| `GET /audit-logs/export.csv` | data:export + audit:view | CSV (audited) |
| `GET /security-events` (`category, user, ip, event_type, success, severity, date_from/to`) · `/summary` · `/types` | security:view | Security events |
| `GET /sessions` (`state, user, user_id, ip`) | security:view | Sessions (no tokens) |
| `POST /sessions/{id}/revoke` · `POST /sessions/revoke-by-ip` | security:manage | Revoke |
| `GET /ip-addresses` · `GET /ip-addresses/{ip}` | security:view | IP aggregates and inspection |
| `GET /ip-blocks` · `POST /ip-blocks` `{ip_address, reason, expires_hours?}` · `POST /ip-blocks/{id}/unblock` | security:view / manage | Blocklist |
| `GET /system/health` | system:view | Health, uptime, errors, IP-detection check |
| `GET /reports/users\|transactions\|security` · `.../export.csv` | reports:view / data:export | Reports (export audited) |

New endpoints for every user: `POST /api/auth/logout` and `POST /api/auth/change-password`. `/api/auth/me` now also returns `role`, `permissions` and `must_change_password`.

## 10. Database changes

One new migration, `20261004_…_admin_system.py`. It's additive and keeps all data: existing accounts become `role=user`, `status=active`.

| Change | Details |
|---|---|
| `users` (new columns) | `role`, `status`, `status_reason`, `status_changed_at/by_id/by_email`, `deleted_at`, `must_change_password`, `password_changed_at`, `registration_ip`, `last_login_at`, `last_login_ip`, `last_activity_at` |
| `transactions` (new columns) | `deleted_at`, `deleted_by_id`, `deleted_reason` (soft delete; hidden from all user queries and totals) |
| `user_sessions` (new table) | server-side sessions |
| `audit_logs` (new table) | append-only, with a Postgres trigger |
| `security_events` (new table) | authentication and suspicious-activity events |
| `ip_blocks` (new table) | blocklist with history |
| Indexes | email, role, status, created_at, last activity, IPs, event types, audit actor/target |
| Row-level security | on all new tables, so Supabase's auto-generated REST API can't read them |

```bash
alembic upgrade head      # apply (Render does this on every start)
alembic downgrade -1      # undo this migration (drops the new tables/columns)
```

## 11. Production deployment

What changes when you deploy this version:

1. **Start command** (already in `render.yaml`): `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. The old `--proxy-headers --forwarded-allow-ips "*"` flags were removed because they made the client IP spoofable. If your service wasn't created from the Blueprint, update the start command by hand in Render → Settings.
2. **New environment variables** on the API service:

   | Key | Value |
   |---|---|
   | `CLIENT_IP_HEADERS` | `true-client-ip,cf-connecting-ip` |
   | `INITIAL_SUPER_ADMIN_EMAIL` | your registered email (optional; see section 1) |
   | `ADMIN_SESSION_HOURS` | `12` (optional) |
   | `ADMIN_IDLE_TIMEOUT_MINUTES` | `60` (optional) |
   | `LOCKOUT_THRESHOLD` / `LOCKOUT_MINUTES` | `5` / `15` (optional) |

3. **Everyone logs in once more** after the deploy. Old tokens have no session id and are rejected on purpose.
4. **Check IP detection:** System health → *Your request* should show your real public IP. If it shows a `10.x` address, the Cloudflare header isn't arriving. Don't block IPs until this is right, because everyone would share one address.
5. **Static site headers:** `render.yaml` now adds a Content-Security-Policy and Referrer-Policy. If you manage headers by hand, add them under Static Site → Headers.
6. **Nothing else changes:** CORS (Bearer tokens, no cookies), HTTPS (Render) and `VITE_API_URL` stay as they are.

## 12. Security design notes

| Threat | Mitigation |
|---|---|
| Privilege escalation | Server-side permission check on every admin route; role only via password-confirmed super-admin endpoints; no self-actions; rank check (`can_act_on`); last-super-admin guard; sessions revoked on role change |
| Mass assignment | `extra="forbid"` on register, profile-edit and admin request bodies; explicit field lists |
| IDOR | User APIs always filter by the token's user id; admin APIs are permission-gated; admin-on-admin actions need super admin |
| Session theft / fixation | Server-side sessions, new session per login, revocation, admin idle timeout, CSP on the frontend |
| CSRF | Not applicable: auth is a Bearer header, not a cookie |
| Brute force | Per-IP limit + per-account temporary lockout + re-auth limit; all recorded |
| IP spoofing | `X-Forwarded-For` never trusted; only Cloudflare-overwritten headers, configured explicitly |
| XSS | React escaping, no raw HTML rendering, CSP `script-src 'self'` |
| SQL injection | SQLAlchemy parameters only; no string-built SQL |
| Sensitive data exposure | No hashes/tokens/secrets in any response or log; masked references; receipt text hidden from admins |
| Audit tampering | Append-only (no endpoints, ORM guard, DB trigger), written atomically with the action |
| Log flooding | Denied-access events throttled per user and path; blocked-IP events throttled per IP; suspicious flags deduplicated |

## 13. Known limitations

- **Rate limits, the IP-block cache and system counters live in one server's memory.** That's fine on a single Render instance. With several instances, move rate limiting to Redis. Request and error counts reset on restart.
- **Recent errors on the System page** are the last 50 since the process started. Full details are in Render's logs.
- **No email:** password resets hand a temporary password to the admin, who passes it on.
- **Lockout can be triggered by an attacker** (15-minute lockout for a known email). That's the usual trade-off; it's temporary and recorded.
- **IP blocking is per exact address.** Mobile carriers and offices share IPs, so block carefully.
- **The device/browser label** is a best-effort guess from the user agent.
- **Dashboard days use `APP_TIMEZONE` on PostgreSQL.** Tests run on SQLite, where days are UTC.
