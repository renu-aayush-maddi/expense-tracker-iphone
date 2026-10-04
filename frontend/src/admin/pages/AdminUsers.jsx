import { useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Alert from "../../components/Alert";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { formatCurrency, formatDate, formatDateTime } from "../../utils/format";
import { adminService } from "../adminService";
import { clean, PagedFooter, SortHeader } from "../components/AdminTable";
import { RoleBadge, StatusBadge, shortId } from "../components/Badges";

export default function AdminUsers() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const sort = { sort_by: filters.sort_by || "created", sort_order: filters.sort_order || "desc" };
  const { data, loading, error } = useApi(() => adminService.users({ page_size: 25, ...filters }), [params.toString()]);

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
          <h1>{filters.status === "blocked" ? "Blocked users" : "Users"}</h1>
          <p className="muted">{data ? `${data.total} account${data.total === 1 ? "" : "s"}` : "Accounts on the platform"}</p>
        </div>
      </div>

      <div className="card filters">
        <div className="filters-grid">
          <label className="field span-2">
            <span>Search</span>
            <input type="search" placeholder="Email or name" defaultValue={filters.q || ""}
              onKeyDown={(e) => e.key === "Enter" && update({ q: e.target.value })}
              onBlur={(e) => e.target.value !== (filters.q || "") && update({ q: e.target.value })} />
          </label>
          <label className="field">
            <span>Role</span>
            <select value={filters.role || ""} onChange={set("role")}>
              <option value="">All</option>
              <option value="user">User</option>
              <option value="read_only_admin">Read-only admin</option>
              <option value="admin">Admin</option>
              <option value="super_admin">Super admin</option>
            </select>
          </label>
          <label className="field">
            <span>Status</span>
            <select value={filters.status || ""} onChange={set("status")}>
              <option value="">All (not deleted)</option>
              {["active", "blocked", "suspended", "disabled", "deleted"].map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Registered from</span>
            <input type="date" value={filters.created_from || ""} onChange={set("created_from")} />
          </label>
          <label className="field">
            <span>Registered to</span>
            <input type="date" value={filters.created_to || ""} onChange={set("created_to")} />
          </label>
          <label className="field">
            <span>Active from</span>
            <input type="date" value={filters.active_from || ""} onChange={set("active_from")} />
          </label>
          <label className="field">
            <span>Active to</span>
            <input type="date" value={filters.active_to || ""} onChange={set("active_to")} />
          </label>
        </div>
        {Object.keys(filters).some((k) => !["page", "sort_by", "sort_order"].includes(k)) && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setParams({})}>Clear filters</button>
        )}
      </div>

      {error && <Alert type="error">{error.message}</Alert>}
      <section className="card">
        {loading && !data ? <Loading /> : data && (
          <div className={loading ? "is-refreshing" : ""}>
            <div className="table-wrap">
              <table className="table admin-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <SortHeader label="User" field="email" sort={sort} onSort={(s) => update(s)} />
                    <SortHeader label="Role" field="role" sort={sort} onSort={(s) => update(s)} />
                    <SortHeader label="Status" field="status" sort={sort} onSort={(s) => update(s)} />
                    <SortHeader label="Created · signup IP" field="created" sort={sort} onSort={(s) => update(s)} />
                    <SortHeader label="Last login · IP" field="last_login" sort={sort} onSort={(s) => update(s)} />
                    <SortHeader label="Last activity" field="last_activity" sort={sort} onSort={(s) => update(s)} />
                    <SortHeader label="Txns" field="transactions" sort={sort} onSort={(s) => update(s)} className="num" />
                    <SortHeader label="Total" field="total" sort={sort} onSort={(s) => update(s)} className="num" />
                    <th className="num">Sessions</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((u) => (
                    <tr key={u.id} className="clickable" tabIndex={0} onClick={() => navigate(`/admin/users/${u.id}`)}
                      onKeyDown={(e) => e.key === "Enter" && navigate(`/admin/users/${u.id}`)}>
                      <td className="mono small">{shortId(u.id)}</td>
                      <td>
                        <div className="cell-strong">{u.full_name || "—"}</div>
                        <div className="small muted">{u.email}</div>
                      </td>
                      <td><RoleBadge role={u.role} /></td>
                      <td><StatusBadge status={u.status} /></td>
                      <td className="small nowrap" title={formatDateTime(u.created_at)}>
                        {formatDate(u.created_at)}<div className="mono muted">{u.registration_ip || "—"}</div>
                      </td>
                      <td className="small nowrap" title={u.last_login_at ? formatDateTime(u.last_login_at) : ""}>
                        {u.last_login_at ? formatDate(u.last_login_at) : "Never"}<div className="mono muted">{u.last_login_ip || "—"}</div>
                      </td>
                      <td className="small nowrap">{u.last_activity_at ? formatDateTime(u.last_activity_at) : "—"}</td>
                      <td className="num">{u.transaction_count}</td>
                      <td className="num nowrap">{formatCurrency(u.transaction_total)}</td>
                      <td className="num">{u.active_sessions}</td>
                      <td><Link to={`/admin/users/${u.id}`} onClick={(e) => e.stopPropagation()}>Manage →</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.items.length === 0 && <p className="empty">No users match these filters.</p>}
            </div>
            <PagedFooter data={data} onPage={(page) => update({ page: String(page) }, true)} />
          </div>
        )}
      </section>
    </div>
  );
}
