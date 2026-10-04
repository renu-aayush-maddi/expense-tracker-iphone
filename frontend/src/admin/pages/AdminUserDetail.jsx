import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import Alert from "../../components/Alert";
import ColumnChart from "../../components/charts/ColumnChart";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { formatCurrency, formatDate, formatDateTime } from "../../utils/format";
import { adminService, can, PERMS, ROLE_LABELS } from "../adminService";
import { ResultBadge, RoleBadge, SeverityBadge, StatusBadge } from "../components/Badges";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";

const ACTIONS = {
  block: {
    title: "Block user", actionLabel: "Block user", danger: true, requireReason: true,
    consequences: "They are logged out of every device immediately, can't log in, and their import Shortcut stops working. Their data stays intact.",
  },
  unblock: { title: "Unblock user", actionLabel: "Unblock", requireReason: true, reasonOptional: true },
  disable: {
    title: "Disable account", actionLabel: "Disable", danger: true, requireReason: true,
    consequences: "All sessions are revoked and the account can't be used until it's enabled again.",
  },
  enable: { title: "Enable account", actionLabel: "Enable", requireReason: true, reasonOptional: true },
  suspend: {
    title: "Suspend account", actionLabel: "Suspend", danger: true, requireReason: true,
    consequences: "A temporary hold: all sessions are revoked until you enable the account again.",
  },
  "force-logout": {
    title: "Log out of all devices", actionLabel: "Revoke all sessions", danger: true, requireReason: true, reasonOptional: true,
    consequences: "Every active session for this account ends now. They can log in again.",
  },
  "reset-password": {
    title: "Reset password", actionLabel: "Reset password", danger: true, requirePassword: true,
    requireReason: true, reasonOptional: true,
    consequences: "Their current password stops working and all sessions end. You'll get a one-time temporary password to give them; they must change it when they log in.",
  },
  delete: {
    title: "Delete user", actionLabel: "Delete user", danger: true, requirePassword: true, confirmText: "DELETE",
    requireReason: true, reasonOptional: true,
    consequences: "The account is deactivated and hidden, sessions and import tokens are revoked. Transactions are kept (soft delete) and a super admin can restore it.",
  },
  restore: { title: "Restore user", actionLabel: "Restore", requirePassword: true, requireReason: true, reasonOptional: true },
};

function Field({ label, children }) {
  return (
    <div className="detail">
      <dt>{label}</dt>
      <dd>{children ?? "—"}</dd>
    </div>
  );
}

export default function AdminUserDetail() {
  const { id } = useParams();
  const { user: me } = useAuth();
  const notify = useToast();
  const [tab, setTab] = useState("overview");
  const [dialog, setDialog] = useState(null); // action key
  const [newRole, setNewRole] = useState("user");
  const [tempPassword, setTempPassword] = useState(null);
  const [editing, setEditing] = useState(null); // {full_name, email}
  const [editError, setEditError] = useState("");
  const { data: user, loading, error, setData, reload } = useApi(() => adminService.user(id), [id]);

  const canManage = can(me, PERMS.usersManage);
  const isSelf = me.id === id;
  // Mirrors the server rule (the server enforces it): only super admins manage admins.
  const canTouch = user && !isSelf && (me.role === "super_admin" || user.role === "user");

  const runAction = async (action, { reason, password }) => {
    if (action === "role") {
      setData(await adminService.userAction(id, "role", { role: newRole, password, reason }));
      notify(`Role changed to ${ROLE_LABELS[newRole]}`);
      return;
    }
    const body = { ...(reason ? { reason } : {}), ...(password ? { password } : {}) };
    const result = await adminService.userAction(id, action, body);
    if (action === "reset-password") {
      setTempPassword(result.temporary_password);
      reload();
    } else if (action === "force-logout") {
      notify(`${result.sessions_revoked} session(s) revoked`);
      reload();
    } else {
      setData(result);
      notify(`${ACTIONS[action].title}: done`);
    }
  };

  const saveProfile = async (event) => {
    event.preventDefault();
    setEditError("");
    try {
      setData(await adminService.updateUser(id, { full_name: editing.full_name, email: editing.email }));
      setEditing(null);
      notify("Profile updated");
    } catch (err) {
      setEditError(err.message);
    }
  };

  if (loading) return <Loading />;
  if (error) return <Alert type="error">{error.status === 404 ? "User not found." : error.message}</Alert>;

  const actionButton = (key, label, style = "btn-secondary") => (
    <button type="button" className={`btn btn-sm ${style}`} onClick={() => setDialog(key)}>{label}</button>
  );
  const inactive = user.status !== "active";

  return (
    <div className="page">
      <Link to="/admin/users" className="back-link">← Users</Link>
      <div className="page-header">
        <div>
          <h1>{user.full_name || user.email}</h1>
          <p className="detail-merchant">
            <span className="muted">{user.email}</span> <RoleBadge role={user.role} /> <StatusBadge status={user.status} />
          </p>
        </div>
        {canManage && canTouch && (
          <div className="page-actions">
            {user.status !== "deleted" && (
              <button type="button" className="btn btn-sm btn-secondary"
                onClick={() => setEditing({ full_name: user.full_name || "", email: user.email })}>Edit profile</button>
            )}
            {user.status === "active" && actionButton("block", "Block", "btn-danger")}
            {user.status === "blocked" && actionButton("unblock", "Unblock")}
            {user.status === "active" && actionButton("suspend", "Suspend")}
            {user.status === "active" && actionButton("disable", "Disable")}
            {["disabled", "suspended"].includes(user.status) && actionButton("enable", "Enable")}
            {user.status !== "deleted" && actionButton("force-logout", "Force logout")}
            {user.status !== "deleted" && actionButton("reset-password", "Reset password")}
            {can(me, PERMS.admins) && user.status !== "deleted" && (
              <button type="button" className="btn btn-sm btn-secondary" onClick={() => { setNewRole(user.role); setDialog("role"); }}>
                Change role
              </button>
            )}
            {can(me, PERMS.usersDelete) && user.status !== "deleted" && actionButton("delete", "Delete", "btn-danger")}
            {can(me, PERMS.usersDelete) && user.status === "deleted" && actionButton("restore", "Restore")}
          </div>
        )}
      </div>
      {isSelf && <Alert type="info">This is your own account. Admin actions on yourself are not allowed.</Alert>}
      {!isSelf && canManage && !canTouch && (
        <Alert type="info">Only a super admin can manage other administrators.</Alert>
      )}

      {inactive && user.status_reason && (
        <Alert type="warning" title={`${user.status[0].toUpperCase()}${user.status.slice(1)} account`}>
          <div>Reason: {user.status_reason}</div>
          <div className="small">By {user.status_changed_by_email || "—"} · {formatDateTime(user.status_changed_at)}</div>
        </Alert>
      )}
      {user.locked && <Alert type="warning">Temporarily locked after {user.failed_logins_recent} failed login attempts.</Alert>}

      <div className="tabs" role="tablist">
        {[["overview", "Overview"], ["activity", "Activity"], ["security", "Security"],
          ...(can(me, PERMS.txView) ? [["finance", "Spending"]] : [])].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "is-active" : ""}
            onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>

      {tab === "overview" && (
        <section className="card">
          <dl className="details-grid details-grid-3">
            <Field label="User ID"><span className="mono small">{user.id}</span></Field>
            <Field label="Name">{user.full_name}</Field>
            <Field label="Email">{user.email}</Field>
            <Field label="Role"><RoleBadge role={user.role} /></Field>
            <Field label="Status"><StatusBadge status={user.status} /></Field>
            <Field label="Created">{formatDateTime(user.created_at)}</Field>
            <Field label="Updated">{formatDateTime(user.updated_at)}</Field>
            <Field label="Last login">{user.last_login_at ? formatDateTime(user.last_login_at) : "Never"}</Field>
            <Field label="Last activity">{user.last_activity_at ? formatDateTime(user.last_activity_at) : "—"}</Field>
            <Field label="Last IP"><span className="mono">{user.last_login_ip}</span></Field>
            <Field label="Signup IP"><span className="mono">{user.registration_ip}</span></Field>
            <Field label="Active sessions">{user.active_sessions}</Field>
            <Field label="Recent failed logins">{user.failed_logins_recent}</Field>
            <Field label="Password changed">{user.password_changed_at ? formatDateTime(user.password_changed_at) : "Never"}</Field>
            <Field label="Must change password">{user.must_change_password ? "Yes" : "No"}</Field>
            <Field label="Transactions">{user.transaction_count}</Field>
            <Field label="Total spending">{formatCurrency(user.transaction_total)}</Field>
          </dl>
        </section>
      )}
      {tab === "activity" && <ActivityTab id={id} />}
      {tab === "security" && <SecurityTab id={id} canRevoke={can(me, PERMS.securityManage) && canTouch} onChange={reload} />}
      {tab === "finance" && <FinanceTab id={id} />}

      <ConfirmDialog
        open={Boolean(dialog)}
        {...(ACTIONS[dialog] || { title: "Change role", actionLabel: "Change role", requirePassword: true, requireReason: true,
          reasonOptional: true, danger: true,
          consequences: "Their sessions end so the new permissions apply on their next login." })}
        onClose={() => setDialog(null)}
        onConfirm={(values) => runAction(dialog, values)}
      >
        <div className="confirm-target">
          <div><span className="muted">User:</span> {user.full_name || "—"}</div>
          <div><span className="muted">Email:</span> {user.email}</div>
        </div>
        {dialog === "role" && (
          <label className="field">
            <span>New role</span>
            <select value={newRole} onChange={(e) => setNewRole(e.target.value)}>
              {Object.entries(ROLE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        )}
      </ConfirmDialog>

      {tempPassword && (
        <div className="modal-backdrop">
          <div className="modal" role="dialog" aria-modal="true">
            <h2>Temporary password</h2>
            <Alert type="warning">Shown only once. Give it to the user through a safe channel. They must change it at login.</Alert>
            <div className="copy-field">
              <input type="text" readOnly value={tempPassword} className="mono" onFocus={(e) => e.target.select()} />
              <button type="button" className="btn btn-secondary" onClick={() => navigator.clipboard?.writeText(tempPassword)}>Copy</button>
            </div>
            <div className="modal-actions">
              <button type="button" className="btn btn-primary" onClick={() => setTempPassword(null)}>Done</button>
            </div>
          </div>
        </div>
      )}

      {editing && (
        <div className="modal-backdrop">
          <form className="modal" onSubmit={saveProfile} role="dialog" aria-modal="true">
            <h2>Edit profile</h2>
            {editError && <Alert type="error">{editError}</Alert>}
            <label className="field">
              <span>Name</span>
              <input type="text" maxLength={120} value={editing.full_name} onChange={(e) => setEditing({ ...editing, full_name: e.target.value })} />
            </label>
            <label className="field">
              <span>Email</span>
              <input type="email" value={editing.email} onChange={(e) => setEditing({ ...editing, email: e.target.value })} />
            </label>
            <p className="muted small">Role and status can't be changed here. Use the dedicated actions (audited).</p>
            <div className="modal-actions">
              <button type="button" className="btn btn-secondary" onClick={() => setEditing(null)}>Cancel</button>
              <button type="submit" className="btn btn-primary">Save</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

const EVENT_LABELS = {
  login_success: "Successful login", login_failed: "Failed login", login_blocked: "Login blocked", logout: "Logged out",
  register: "Registered", password_changed: "Password changed", password_reset: "Password reset by admin",
  account_locked: "Account locked", session_revoked: "Session revoked", import_request: "Import request",
  new_ip_login: "Login from a new IP",
};

function ActivityTab({ id }) {
  const { data, loading, error } = useApi(() => adminService.userActivity(id), [id]);
  if (loading) return <Loading />;
  if (error) return <Alert type="error">{error.message}</Alert>;
  if (!data.length) return <p className="empty">No activity yet.</p>;
  return (
    <section className="card">
      <ol className="timeline">
        {data.map((item, i) => (
          <li key={i} className={`timeline-item timeline-${item.kind}`}>
            <div className="timeline-time small muted">{formatDateTime(item.at)}</div>
            <div>
              <strong>{item.kind === "admin" ? item.type : item.kind === "security" ? EVENT_LABELS[item.type] || item.type : item.detail}</strong>
              {item.kind === "security" && item.success === false && <span className="result-fail small"> · failed</span>}
              <div className="small muted">
                {item.kind === "transaction" ? "" : item.detail || ""}
                {item.ip && <> · IP <span className="mono">{item.ip}</span></>}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function SecurityTab({ id, canRevoke, onChange }) {
  const notify = useToast();
  const { data, loading, error, reload } = useApi(() => adminService.userSecurity(id), [id]);
  const [revoking, setRevoking] = useState(null);
  if (loading) return <Loading />;
  if (error) return <Alert type="error">{error.message}</Alert>;
  return (
    <>
      <div className="grid-2">
        <section className="card">
          <h2>Known IP addresses</h2>
          <table className="table">
            <thead><tr><th>IP</th><th>First seen</th><th>Last seen</th><th className="num">Events</th></tr></thead>
            <tbody>
              {data.known_ips.map((ip) => (
                <tr key={ip.ip_address}>
                  <td className="mono"><Link to={`/admin/ip-addresses?ip=${encodeURIComponent(ip.ip_address)}`}>{ip.ip_address}</Link></td>
                  <td className="small">{formatDateTime(ip.first_seen)}</td>
                  <td className="small">{formatDateTime(ip.last_seen)}</td>
                  <td className="num">{ip.events}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="card">
          <h2>Sessions</h2>
          <table className="table">
            <thead><tr><th>Device</th><th>IP</th><th>Last seen</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data.sessions.map((s) => (
                <tr key={s.id}>
                  <td className="small">{s.device}</td>
                  <td className="mono small">{s.ip_address}</td>
                  <td className="small">{formatDateTime(s.last_seen_at)}</td>
                  <td className="small">{s.status}{s.revoked_reason ? ` (${s.revoked_reason})` : ""}</td>
                  <td>{canRevoke && s.status === "active" && (
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRevoking(s)}>Revoke</button>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
      <section className="card">
        <h2>Security events</h2>
        <table className="table">
          <thead><tr><th>Time</th><th>Event</th><th>Result</th><th>IP</th><th>Reason</th><th>Severity</th></tr></thead>
          <tbody>
            {data.events.map((e) => (
              <tr key={e.id}>
                <td className="small nowrap">{formatDateTime(e.created_at)}</td>
                <td>{EVENT_LABELS[e.event_type] || e.event_type}</td>
                <td><ResultBadge ok={e.success} /></td>
                <td className="mono small">{e.ip_address}</td>
                <td className="small">{e.reason || "—"}</td>
                <td><SeverityBadge severity={e.severity} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <ConfirmDialog open={Boolean(revoking)} title="Revoke session" actionLabel="Revoke" danger requireReason reasonOptional
        consequences="This device is logged out immediately." onClose={() => setRevoking(null)}
        onConfirm={async ({ reason }) => {
          await adminService.revokeSession(revoking.id, reason ? { reason } : {});
          notify("Session revoked");
          reload();
          onChange();
        }}>
        <div className="confirm-target">{revoking?.device} · <span className="mono">{revoking?.ip_address}</span></div>
      </ConfirmDialog>
    </>
  );
}

function FinanceTab({ id }) {
  const { data, loading, error } = useApi(() => adminService.userFinance(id), [id]);
  if (loading) return <Loading />;
  if (error) return <Alert type="error">{error.message}</Alert>;
  return (
    <>
      <div className="metrics-grid">
        <div className="metric"><div className="metric-label">Transactions</div><div className="metric-value">{data.transaction_count}</div></div>
        <div className="metric"><div className="metric-label">Total spending</div><div className="metric-value">{formatCurrency(data.total_spending)}</div></div>
        <div className="metric"><div className="metric-label">Average</div><div className="metric-value">{formatCurrency(data.average_transaction)}</div></div>
        <div className="metric"><div className="metric-label">Highest</div><div className="metric-value">{formatCurrency(data.highest_transaction)}</div></div>
      </div>
      <div className="grid-2 grid-2-wide">
        <section className="card">
          <h2>Spending over time</h2>
          <ColumnChart data={data.monthly} tickFormatter={(l) => l.split(" ")[0]} tableCaption="Monthly spending" />
        </section>
        <section className="card">
          <h2>Recent transactions</h2>
          <p className="muted small">References are masked. Notes and receipt text are never shown to admins.</p>
          <table className="table">
            <tbody>
              {data.recent_transactions.map((t) => (
                <tr key={t.id}>
                  <td className="small nowrap">{formatDate(t.transaction_date)}</td>
                  <td><div className="cell-strong">{t.merchant_name}</div><div className="small muted">{t.category} · {t.source}{t.utr_masked ? ` · UTR ${t.utr_masked}` : ""}</div></td>
                  <td className="num amount">{formatCurrency(t.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.recent_transactions.length === 0 && <p className="empty">No transactions.</p>}
        </section>
      </div>
    </>
  );
}
