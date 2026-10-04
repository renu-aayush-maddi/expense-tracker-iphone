import { useState } from "react";
import { Link } from "react-router-dom";
import Alert from "../../components/Alert";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { formatDateTime } from "../../utils/format";
import { adminService, ROLE_LABELS } from "../adminService";
import { RoleBadge, StatusBadge } from "../components/Badges";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";

const PERMISSION_TABLE = [
  ["View dashboard, users, transactions, audit logs, security, reports, system", true, true, true],
  ["Manage users (edit, block, disable, force logout, reset password)", false, true, true],
  ["Soft-delete / restore transactions", false, true, true],
  ["Revoke sessions, block IPs", false, true, true],
  ["Export CSV", false, true, true],
  ["Manage other admins and roles", false, false, true],
  ["Delete / restore user accounts", false, false, true],
];

export default function AdminAdmins() {
  const { user: me } = useAuth();
  const notify = useToast();
  const { data, loading, error, reload } = useApi(() => adminService.admins(), []);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ email: "", role: "read_only_admin" });
  const [changing, setChanging] = useState(null);
  const [newRole, setNewRole] = useState("admin");
  const [activityFor, setActivityFor] = useState(null);
  const activity = useApi(() => (activityFor ? adminService.adminActivity(activityFor.id) : Promise.resolve(null)), [activityFor?.id]);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Admins</h1>
          <p className="muted">Super admins only. Every change requires your password and is audited.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>Add admin…</button>
      </div>
      {error && <Alert type="error">{error.message}</Alert>}
      <section className="card">
        {loading ? <Loading /> : data && (
          <table className="table admin-table">
            <thead><tr><th>Admin</th><th>Role</th><th>Status</th><th>Last login</th><th>Last IP</th><th /></tr></thead>
            <tbody>
              {data.items.map((a) => (
                <tr key={a.id}>
                  <td><Link to={`/admin/users/${a.id}`}>{a.email}</Link>{a.id === me.id && <span className="muted small"> (you)</span>}</td>
                  <td><RoleBadge role={a.role} /></td>
                  <td><StatusBadge status={a.status} /></td>
                  <td className="small">{a.last_login_at ? formatDateTime(a.last_login_at) : "Never"}</td>
                  <td className="mono small">{a.last_login_ip || "—"}</td>
                  <td className="nowrap">
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => setActivityFor(a)}>Activity</button>
                    {a.id !== me.id && (
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setChanging(a); setNewRole(a.role); }}>Change role</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>Role permissions</h2>
        <table className="table">
          <thead><tr><th>Permission</th><th>Read-only admin</th><th>Admin</th><th>Super admin</th></tr></thead>
          <tbody>
            {PERMISSION_TABLE.map(([label, ...roles]) => (
              <tr key={label}>
                <td>{label}</td>
                {roles.map((allowed, i) => <td key={i} className={allowed ? "result-ok" : "muted"}>{allowed ? "✓ Yes" : "— No"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">Enforced on the server for every request. Admins can't act on themselves, and only super admins can act on other admins.</p>
      </section>

      {activityFor && (
        <section className="card">
          <div className="card-header">
            <h2>Recent actions by {activityFor.email}</h2>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setActivityFor(null)}>Close ×</button>
          </div>
          {activity.loading && <Loading />}
          {activity.data && (activity.data.length === 0 ? <p className="empty">No actions yet.</p> : (
            <ul className="feed">
              {activity.data.map((a) => (
                <li key={a.id}><code>{a.action}</code>
                  <div className="small muted">{a.target_email ? `→ ${a.target_email} · ` : ""}{formatDateTime(a.created_at)}</div></li>
              ))}
            </ul>
          ))}
        </section>
      )}

      <ConfirmDialog open={adding} title="Add admin" actionLabel="Grant admin role" danger requirePassword requireReason reasonOptional
        consequences="The account must already exist (they register normally first). Their sessions end so the new role applies on next login."
        onClose={() => setAdding(false)}
        onConfirm={async ({ password, reason }) => {
          await adminService.addAdmin({ email: form.email.trim(), role: form.role, password, reason });
          notify(`${form.email} is now ${ROLE_LABELS[form.role]}`);
          setForm({ email: "", role: "read_only_admin" });
          reload();
        }}>
        <label className="field"><span>Account email</span>
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
        <label className="field"><span>Role</span>
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="read_only_admin">Read-only admin</option><option value="admin">Admin</option><option value="super_admin">Super admin</option>
          </select></label>
      </ConfirmDialog>

      <ConfirmDialog open={Boolean(changing)} title="Change admin role" actionLabel="Change role" danger requirePassword
        requireReason reasonOptional consequences="Choosing “User” removes admin access. Their sessions end immediately."
        onClose={() => setChanging(null)}
        onConfirm={async ({ password, reason }) => {
          await adminService.userAction(changing.id, "role", { role: newRole, password, reason });
          notify(`Role changed to ${ROLE_LABELS[newRole]}`);
          reload();
        }}>
        <div className="confirm-target">{changing?.email}</div>
        <label className="field"><span>New role</span>
          <select value={newRole} onChange={(e) => setNewRole(e.target.value)}>
            {Object.entries(ROLE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
      </ConfirmDialog>
    </div>
  );
}
