import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Alert from "../../components/Alert";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { formatDateTime } from "../../utils/format";
import { adminService } from "../adminService";
import { clean, PagedFooter } from "../components/AdminTable";
import { ResultBadge, SeverityBadge } from "../components/Badges";

export const EVENT_LABELS = {
  login_success: "Successful login", login_failed: "Failed login", login_blocked: "Blocked login", logout: "Logout",
  register: "Registration", password_changed: "Password change", password_reset: "Password reset (admin)",
  account_locked: "Account locked", session_revoked: "Session revoked", blocked_ip_request: "Request from blocked IP",
  import_request: "Import request", reauth_failed: "Admin re-auth failed", admin_access_denied: "Admin access denied",
  admin_permission_denied: "Admin permission denied", suspicious_failed_logins: "Repeated failed logins",
  suspicious_many_ips: "Logins from many IPs", suspicious_credential_stuffing: "Credential stuffing",
  new_ip_login: "Login from new IP", suspicious_blocked_requests: "Repeated blocked requests",
  suspicious_registrations: "Many signups from one IP",
};

export default function AdminSecurity() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const tab = filters.tab || "auth";
  const query = { ...filters, category: tab === "suspicious" ? "suspicious" : tab === "auth" ? "auth" : "all", page_size: 50 };
  delete query.tab;
  const { data, loading, error } = useApi(() => adminService.securityEvents(query), [params.toString()]);
  const { data: summary } = useApi(() => adminService.securitySummary(), []);
  const { data: types } = useApi(() => adminService.securityEventTypes(), []);

  const update = (changes, keepPage = false) => {
    const next = clean({ ...filters, ...changes });
    if (!keepPage) delete next.page;
    setParams(next);
  };
  const set = (field) => (e) => update({ [field]: e.target.value });

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Login & security</h1>
          <p className="muted">Authentication activity and automatically flagged patterns. Nothing is auto-blocked; you decide.</p>
        </div>
      </div>

      {summary && summary.length > 0 && (
        <section className="card">
          <h2>Flagged in the last 7 days</h2>
          <div className="metrics-grid">
            {summary.map((s) => (
              <button key={s.event_type + s.severity} type="button" className="metric metric-link"
                onClick={() => update({ tab: "suspicious", event_type: s.event_type })}>
                <div className="metric-label"><SeverityBadge severity={s.severity} /></div>
                <div className="metric-value">{s.count}</div>
                <div className="metric-hint">{EVENT_LABELS[s.event_type] || s.event_type}</div>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="tabs" role="tablist">
        {[["auth", "Authentication"], ["suspicious", "Suspicious activity"], ["all", "All events"]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "is-active" : ""}
            onClick={() => setParams(clean({ tab: key }))}>{label}</button>
        ))}
      </div>

      <div className="card filters">
        <div className="filters-grid">
          <label className="field"><span>User email</span>
            <input type="search" defaultValue={filters.user || ""}
              onKeyDown={(e) => e.key === "Enter" && update({ user: e.target.value })}
              onBlur={(e) => e.target.value !== (filters.user || "") && update({ user: e.target.value })} /></label>
          <label className="field"><span>IP</span>
            <input type="search" defaultValue={filters.ip || ""}
              onKeyDown={(e) => e.key === "Enter" && update({ ip: e.target.value })}
              onBlur={(e) => e.target.value !== (filters.ip || "") && update({ ip: e.target.value })} /></label>
          <label className="field"><span>Event</span>
            <select value={filters.event_type || ""} onChange={set("event_type")}>
              <option value="">All</option>
              {(types || []).map((t) => <option key={t} value={t}>{EVENT_LABELS[t] || t}</option>)}
            </select></label>
          <label className="field"><span>Result</span>
            <select value={filters.success ?? ""} onChange={set("success")}>
              <option value="">All</option><option value="true">Success</option><option value="false">Failed</option>
            </select></label>
          <label className="field"><span>From</span><input type="date" value={filters.date_from || ""} onChange={set("date_from")} /></label>
          <label className="field"><span>To</span><input type="date" value={filters.date_to || ""} onChange={set("date_to")} /></label>
        </div>
      </div>

      {error && <Alert type="error">{error.message}</Alert>}
      <section className="card">
        {loading && !data ? <Loading /> : data && (
          <div className={loading ? "is-refreshing" : ""}>
            <div className="table-wrap">
              <table className="table admin-table">
                <thead><tr><th>Time</th><th>Event</th><th>User</th><th>IP</th><th>Device</th><th>Result</th><th>Reason</th><th>Severity</th></tr></thead>
                <tbody>
                  {data.items.map((e) => (
                    <tr key={e.id}>
                      <td className="small nowrap">{formatDateTime(e.created_at)}</td>
                      <td>{EVENT_LABELS[e.event_type] || e.event_type}</td>
                      <td className="small">{e.user_id ? <Link to={`/admin/users/${e.user_id}`}>{e.email || "user"}</Link> : e.email || "—"}</td>
                      <td className="mono small">{e.ip_address ? <Link to={`/admin/ip-addresses?ip=${encodeURIComponent(e.ip_address)}`}>{e.ip_address}</Link> : "—"}</td>
                      <td className="small" title={e.user_agent || ""}>{e.device || "—"}</td>
                      <td><ResultBadge ok={e.success} /></td>
                      <td className="small">{e.reason || "—"}</td>
                      <td><SeverityBadge severity={e.severity} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.items.length === 0 && <p className="empty">No events match.</p>}
            </div>
            <PagedFooter data={data} onPage={(page) => update({ page: String(page) }, true)} />
          </div>
        )}
      </section>
    </div>
  );
}
