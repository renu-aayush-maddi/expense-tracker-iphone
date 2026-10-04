import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Alert from "../../components/Alert";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { formatDateTime } from "../../utils/format";
import { adminService, can, PERMS } from "../adminService";
import { clean, PagedFooter } from "../components/AdminTable";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";

export default function AdminSessions() {
  const { user: me } = useAuth();
  const notify = useToast();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const { data, loading, error, reload } = useApi(() => adminService.sessions({ state: "active", page_size: 50, ...filters }),
    [params.toString()]);
  const [revoking, setRevoking] = useState(null);
  const [byIp, setByIp] = useState(false);
  const [ip, setIp] = useState("");
  const manage = can(me, PERMS.securityManage);

  const update = (changes, keepPage = false) => {
    const next = clean({ ...filters, ...changes });
    if (!keepPage) delete next.page;
    setParams(next);
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Sessions</h1>
          <p className="muted">Logged-in devices. Session tokens are never stored or shown.</p>
        </div>
        {manage && <button type="button" className="btn btn-secondary" onClick={() => setByIp(true)}>Revoke all from an IP…</button>}
      </div>
      <div className="card filters">
        <div className="filters-grid">
          <label className="field"><span>Show</span>
            <select value={filters.state || "active"} onChange={(e) => update({ state: e.target.value })}>
              <option value="active">Active only</option><option value="all">All (incl. revoked/expired)</option>
            </select></label>
          <label className="field"><span>User email</span>
            <input type="search" defaultValue={filters.user || ""}
              onKeyDown={(e) => e.key === "Enter" && update({ user: e.target.value })}
              onBlur={(e) => e.target.value !== (filters.user || "") && update({ user: e.target.value })} /></label>
          <label className="field"><span>IP</span>
            <input type="search" defaultValue={filters.ip || ""}
              onKeyDown={(e) => e.key === "Enter" && update({ ip: e.target.value })}
              onBlur={(e) => e.target.value !== (filters.ip || "") && update({ ip: e.target.value })} /></label>
        </div>
      </div>
      {error && <Alert type="error">{error.message}</Alert>}
      <section className="card">
        {loading && !data ? <Loading /> : data && (
          <div className={loading ? "is-refreshing" : ""}>
            <div className="table-wrap">
              <table className="table admin-table">
                <thead><tr><th>User</th><th>Device</th><th>IP</th><th>Created</th><th>Last activity</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {data.items.map((s) => (
                    <tr key={s.id}>
                      <td className="small"><Link to={`/admin/users/${s.user_id}`}>{s.user_email}</Link></td>
                      <td className="small" title={s.user_agent || ""}>{s.device}</td>
                      <td className="mono small">{s.ip_address || "—"}</td>
                      <td className="small nowrap">{formatDateTime(s.created_at)}</td>
                      <td className="small nowrap">{formatDateTime(s.last_seen_at)}</td>
                      <td className="small">
                        <span className={s.status === "active" ? "result-ok" : "muted"}>{s.status === "active" ? "● active" : s.status}</span>
                        {s.revoked_reason && <div className="muted">{s.revoked_reason}</div>}
                      </td>
                      <td>{manage && s.status === "active" && s.user_id !== me.id && (
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRevoking(s)}>Revoke</button>
                      )}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.items.length === 0 && <p className="empty">No sessions match.</p>}
            </div>
            <PagedFooter data={data} onPage={(page) => update({ page: String(page) }, true)} />
          </div>
        )}
      </section>

      <ConfirmDialog open={Boolean(revoking)} title="Revoke session" actionLabel="Revoke session" danger requireReason reasonOptional
        consequences="This device is logged out immediately." onClose={() => setRevoking(null)}
        onConfirm={async ({ reason }) => {
          await adminService.revokeSession(revoking.id, reason ? { reason } : {});
          notify("Session revoked");
          reload();
        }}>
        <div className="confirm-target">{revoking?.user_email} · {revoking?.device} · <span className="mono">{revoking?.ip_address}</span></div>
      </ConfirmDialog>

      <ConfirmDialog open={byIp} title="Revoke all sessions from an IP" actionLabel="Revoke sessions" danger requireReason
        consequences="Every active session from this IP is ended (your own sessions are kept)." onClose={() => setByIp(false)}
        onConfirm={async ({ reason }) => {
          const result = await adminService.revokeSessionsByIp({ ip_address: ip.trim(), reason });
          notify(`${result.sessions_revoked} session(s) revoked`);
          reload();
        }}>
        <label className="field"><span>IP address</span>
          <input type="text" value={ip} onChange={(e) => setIp(e.target.value)} placeholder="203.0.113.7" /></label>
      </ConfirmDialog>
    </div>
  );
}
