import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Alert from "../../components/Alert";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { formatDateTime } from "../../utils/format";
import { adminService, can, PERMS } from "../adminService";
import { clean, PagedFooter } from "../components/AdminTable";
import { ResultBadge, StatusBadge } from "../components/Badges";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { EVENT_LABELS } from "./AdminSecurity";

export default function AdminIpAddresses() {
  const { user: me } = useAuth();
  const notify = useToast();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const tab = filters.tab || "all";
  const manage = can(me, PERMS.securityManage);
  const [blockForm, setBlockForm] = useState(null); // {ip_address, expires_hours}
  const [unblocking, setUnblocking] = useState(null);

  const list = useApi(
    () => (tab === "blocked"
      ? adminService.ipBlocks({ state: filters.state || "active", page: filters.page })
      : adminService.ipAddresses({ q: filters.q, sort_by: filters.sort_by, page: filters.page, page_size: 50 })),
    [params.toString()],
  );
  const inspected = useApi(() => (filters.ip ? adminService.ipAddress(filters.ip) : Promise.resolve(null)), [filters.ip]);

  const update = (changes, keepPage = false) => {
    const next = clean({ ...filters, ...changes });
    if (!keepPage) delete next.page;
    setParams(next);
  };
  const refresh = () => {
    list.reload();
    inspected.reload();
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>IP addresses</h1>
          <p className="muted">Built from security events (logins, signups, imports). Block an IP only when you're sure: it affects everyone on that network.</p>
        </div>
        {manage && <button type="button" className="btn btn-primary" onClick={() => setBlockForm({ ip_address: "", expires_hours: "" })}>Block an IP…</button>}
      </div>

      <div className="tabs" role="tablist">
        {[["all", "All IPs"], ["blocked", "Blocked IPs"]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "is-active" : ""}
            onClick={() => setParams(clean({ tab: key, ip: filters.ip }))}>{label}</button>
        ))}
      </div>

      {filters.ip && (
        <section className="card">
          <div className="card-header">
            <h2>IP <span className="mono">{filters.ip}</span></h2>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => update({ ip: "" })}>Close ×</button>
          </div>
          {inspected.loading && <Loading />}
          {inspected.error && <Alert type="error">{inspected.error.message}</Alert>}
          {inspected.data && (
            <>
              {inspected.data.blocked ? (
                <Alert type="warning" title="Blocked">
                  {inspected.data.active_block.reason} · by {inspected.data.active_block.blocked_by_email} ·{" "}
                  {formatDateTime(inspected.data.active_block.created_at)}
                  {manage && <> · <button type="button" className="link-button" onClick={() => setUnblocking(inspected.data.active_block)}>Unblock</button></>}
                </Alert>
              ) : manage && (
                <button type="button" className="btn btn-danger btn-sm"
                  onClick={() => setBlockForm({ ip_address: filters.ip, expires_hours: "" })}>Block this IP…</button>
              )}
              <div className="grid-2">
                <div>
                  <h3>Users seen from this IP</h3>
                  <table className="table">
                    <tbody>
                      {inspected.data.users.map((u) => (
                        <tr key={u.id}>
                          <td><Link to={`/admin/users/${u.id}`}>{u.email}</Link></td>
                          <td><StatusBadge status={u.status} /></td>
                          <td className="small">{u.events} events · {formatDateTime(u.last_seen)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {inspected.data.users.length === 0 && <p className="empty">No accounts.</p>}
                </div>
                <div>
                  <h3>Recent events</h3>
                  <table className="table">
                    <tbody>
                      {inspected.data.events.slice(0, 20).map((e) => (
                        <tr key={e.id}>
                          <td className="small nowrap">{formatDateTime(e.created_at)}</td>
                          <td className="small">{EVENT_LABELS[e.event_type] || e.event_type}</td>
                          <td><ResultBadge ok={e.success} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </section>
      )}

      {tab === "all" && (
        <div className="card filters">
          <div className="filters-grid">
            <label className="field span-2"><span>Search IP</span>
              <input type="search" defaultValue={filters.q || ""}
                onKeyDown={(e) => e.key === "Enter" && update({ q: e.target.value })}
                onBlur={(e) => e.target.value !== (filters.q || "") && update({ q: e.target.value })} /></label>
            <label className="field"><span>Sort by</span>
              <select value={filters.sort_by || "last_seen"} onChange={(e) => update({ sort_by: e.target.value })}>
                <option value="last_seen">Last seen</option><option value="events">Events</option>
                <option value="failed_logins">Failed logins</option><option value="users">Users</option>
              </select></label>
          </div>
        </div>
      )}

      {list.error && <Alert type="error">{list.error.message}</Alert>}
      <section className="card">
        {list.loading && !list.data ? <Loading /> : list.data && (
          <div className={list.loading ? "is-refreshing" : ""}>
            <div className="table-wrap">
              {tab === "all" ? (
                <table className="table admin-table">
                  <thead><tr><th>IP</th><th>First seen</th><th>Last seen</th><th className="num">Users</th>
                    <th className="num">Events</th><th className="num">Logins ✓</th><th className="num">Logins ✕</th><th>Status</th></tr></thead>
                  <tbody>
                    {list.data.items.map((r) => (
                      <tr key={r.ip_address} className="clickable" tabIndex={0} onClick={() => update({ ip: r.ip_address }, true)}
                        onKeyDown={(e) => e.key === "Enter" && update({ ip: r.ip_address }, true)}>
                        <td className="mono">{r.ip_address}</td>
                        <td className="small nowrap">{formatDateTime(r.first_seen)}</td>
                        <td className="small nowrap">{formatDateTime(r.last_seen)}</td>
                        <td className="num">{r.users}</td>
                        <td className="num">{r.events}</td>
                        <td className="num">{r.successful_logins}</td>
                        <td className="num">{r.failed_logins}</td>
                        <td>{r.blocked ? <span className="result-fail">⛔ blocked</span> : <span className="muted">allowed</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <table className="table admin-table">
                  <thead><tr><th>IP</th><th>Reason</th><th>Blocked by</th><th>Blocked at</th><th>Expires</th><th /></tr></thead>
                  <tbody>
                    {list.data.items.map((b) => (
                      <tr key={b.id}>
                        <td className="mono"><button type="button" className="link-button" onClick={() => update({ ip: b.ip_address }, true)}>{b.ip_address}</button></td>
                        <td className="small">{b.reason}</td>
                        <td className="small">{b.blocked_by_email}</td>
                        <td className="small nowrap">{formatDateTime(b.created_at)}</td>
                        <td className="small">{b.expires_at ? formatDateTime(b.expires_at) : "Never"}</td>
                        <td>{manage && !b.unblocked_at && (
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setUnblocking(b)}>Unblock</button>
                        )}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {list.data.items.length === 0 && <p className="empty">{tab === "blocked" ? "No blocked IPs." : "No IPs recorded yet."}</p>}
            </div>
            <PagedFooter data={list.data} onPage={(page) => update({ page: String(page) }, true)} />
          </div>
        )}
      </section>

      <ConfirmDialog open={Boolean(blockForm)} title="Block IP address" actionLabel="Block IP" danger requireReason
        consequences="All API requests from this IP are rejected, including logins. Shared networks (offices, mobile carriers) can affect many people. You can't block your own current IP."
        onClose={() => setBlockForm(null)}
        onConfirm={async ({ reason }) => {
          await adminService.blockIp({
            ip_address: blockForm.ip_address.trim(), reason,
            ...(blockForm.expires_hours ? { expires_hours: Number(blockForm.expires_hours) } : {}),
          });
          notify("IP blocked");
          refresh();
        }}>
        {blockForm && (
          <div className="form-grid">
            <label className="field"><span>IP address</span>
              <input type="text" value={blockForm.ip_address} onChange={(e) => setBlockForm({ ...blockForm, ip_address: e.target.value })} placeholder="203.0.113.7" /></label>
            <label className="field"><span>Expires after (hours, optional)</span>
              <input type="number" min="1" value={blockForm.expires_hours} onChange={(e) => setBlockForm({ ...blockForm, expires_hours: e.target.value })} placeholder="Never" /></label>
          </div>
        )}
      </ConfirmDialog>

      <ConfirmDialog open={Boolean(unblocking)} title="Unblock IP address" actionLabel="Unblock" requireReason reasonOptional
        onClose={() => setUnblocking(null)}
        onConfirm={async ({ reason }) => {
          await adminService.unblockIp(unblocking.id, reason ? { reason } : {});
          notify("IP unblocked");
          refresh();
        }}>
        <div className="confirm-target mono">{unblocking?.ip_address}</div>
      </ConfirmDialog>
    </div>
  );
}
