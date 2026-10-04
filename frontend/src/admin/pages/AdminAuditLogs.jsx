import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Alert from "../../components/Alert";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { formatDateTime } from "../../utils/format";
import { adminService, can, PERMS } from "../adminService";
import { clean, PagedFooter } from "../components/AdminTable";
import JsonView from "../components/JsonView";
import { useToast } from "../components/Toast";

export default function AdminAuditLogs() {
  const { user: me } = useAuth();
  const notify = useToast();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const { data, loading, error } = useApi(() => adminService.auditLogs({ page_size: 50, ...filters }), [params.toString()]);
  const { data: actions } = useApi(() => adminService.auditActions(), []);
  const [selected, setSelected] = useState(null);

  const update = (changes, keepPage = false) => {
    const next = clean({ ...filters, ...changes });
    if (!keepPage) delete next.page;
    setParams(next);
  };
  const set = (field) => (e) => update({ [field]: e.target.value });

  const exportCsv = async () => {
    try {
      const { page: _p, ...rest } = filters;
      await adminService.exportAuditLogs(rest);
      notify("Export downloaded (recorded in the audit log)");
    } catch (err) {
      notify(err.message, "error");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Audit logs</h1>
          <p className="muted">Append-only record of admin and sensitive actions. Entries can't be edited or deleted.</p>
        </div>
        {can(me, PERMS.export) && <button type="button" className="btn btn-secondary" onClick={exportCsv}>Export CSV</button>}
      </div>
      <div className="card filters">
        <div className="filters-grid">
          <label className="field span-2"><span>Search</span>
            <input type="search" placeholder="Action, email, resource, IP" defaultValue={filters.q || ""}
              onKeyDown={(e) => e.key === "Enter" && update({ q: e.target.value })}
              onBlur={(e) => e.target.value !== (filters.q || "") && update({ q: e.target.value })} /></label>
          <label className="field"><span>Action</span>
            <select value={filters.action || ""} onChange={set("action")}>
              <option value="">All</option>
              {(actions || []).map((a) => <option key={a}>{a}</option>)}
            </select></label>
          <label className="field"><span>Result</span>
            <select value={filters.result || ""} onChange={set("result")}>
              <option value="">All</option><option value="success">Success</option><option value="failure">Failure</option>
            </select></label>
          <label className="field"><span>From</span><input type="date" value={filters.date_from || ""} onChange={set("date_from")} /></label>
          <label className="field"><span>To</span><input type="date" value={filters.date_to || ""} onChange={set("date_to")} /></label>
          <label className="field"><span>Order</span>
            <select value={filters.sort_order || "desc"} onChange={set("sort_order")}>
              <option value="desc">Newest first</option><option value="asc">Oldest first</option>
            </select></label>
        </div>
      </div>
      {error && <Alert type="error">{error.message}</Alert>}
      <section className="card">
        {loading && !data ? <Loading /> : data && (
          <div className={loading ? "is-refreshing" : ""}>
            <div className="table-wrap">
              <table className="table admin-table">
                <thead><tr><th>Time</th><th>Admin</th><th>Action</th><th>Target</th><th>Resource</th><th>IP</th><th>Result</th></tr></thead>
                <tbody>
                  {data.items.map((a) => (
                    <tr key={a.id} className="clickable" tabIndex={0} onClick={() => setSelected(a)}
                      onKeyDown={(e) => e.key === "Enter" && setSelected(a)}>
                      <td className="small nowrap">{formatDateTime(a.created_at)}</td>
                      <td className="small">{a.actor_email || "system"}<div className="muted">{a.actor_role}</div></td>
                      <td><code>{a.action}</code></td>
                      <td className="small">{a.target_email || "—"}</td>
                      <td className="small">{a.resource_type ? `${a.resource_type}` : "—"}</td>
                      <td className="mono small">{a.ip_address || "—"}</td>
                      <td className={a.result === "success" ? "result-ok" : "result-fail"}>{a.result === "success" ? "✓" : "✕"} {a.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.items.length === 0 && <p className="empty">No audit entries match.</p>}
            </div>
            <PagedFooter data={data} onPage={(page) => update({ page: String(page) }, true)} />
          </div>
        )}
      </section>

      {selected && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setSelected(null)}>
          <div className="modal modal-wide" role="dialog" aria-modal="true">
            <h2><code>{selected.action}</code></h2>
            <dl className="details-grid">
              <div className="detail"><dt>Time</dt><dd>{formatDateTime(selected.created_at)}</dd></div>
              <div className="detail"><dt>Result</dt><dd>{selected.result}</dd></div>
              <div className="detail"><dt>Admin</dt><dd>{selected.actor_email || "system"} {selected.actor_role && `(${selected.actor_role})`}</dd></div>
              <div className="detail"><dt>Target user</dt><dd>{selected.target_email || "—"}</dd></div>
              <div className="detail"><dt>Resource</dt><dd className="mono small">{selected.resource_type || "—"} {selected.resource_id}</dd></div>
              <div className="detail"><dt>IP</dt><dd className="mono">{selected.ip_address || "—"}</dd></div>
              <div className="detail span-2"><dt>User agent</dt><dd className="small">{selected.user_agent || "—"}</dd></div>
            </dl>
            <h3>Details</h3>
            <JsonView value={selected.details} />
            <div className="modal-actions">
              <button type="button" className="btn btn-primary" onClick={() => setSelected(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
