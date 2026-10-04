import { useState } from "react";
import { Link } from "react-router-dom";
import Alert from "../../components/Alert";
import ColumnChart from "../../components/charts/ColumnChart";
import StackedColumnChart from "../../components/charts/StackedColumnChart";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { formatCurrency, formatDateTime } from "../../utils/format";
import { adminService } from "../adminService";
import RangePicker, { rangeParams } from "../components/RangePicker";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dayLabel = (iso) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
const toChart = (series) => series.map((p) => ({ label: p.date, total: p.value }));

export function formatUptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

function Metric({ label, value, hint, to }) {
  const body = (
    <>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {hint && <div className="metric-hint">{hint}</div>}
    </>
  );
  return to ? <Link to={to} className="metric metric-link">{body}</Link> : <div className="metric">{body}</div>;
}

export const COMPONENT_LABELS = { api: "API", database: "Database", authentication: "Authentication", phonepe_import: "PhonePe import" };

export function HealthPill({ status }) {
  const ok = status === "healthy";
  return <span className={`health-pill ${ok ? "is-ok" : "is-bad"}`}>{ok ? "✓ Healthy" : "✕ " + (status || "Unknown")}</span>;
}

export default function AdminDashboard() {
  const [range, setRange] = useState({ range: "30d" });
  const params = rangeParams(range);
  const { data, loading, error } = useApi(() => (params ? adminService.dashboard(params) : Promise.resolve(null)),
    [JSON.stringify(params)]);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Admin dashboard</h1>
          <p className="muted">Platform overview{data ? ` · times in ${data.range.timezone}` : ""}</p>
        </div>
        <RangePicker value={range} onChange={setRange} />
      </div>

      {error && <Alert type="error">{error.message}</Alert>}
      {!params && <Alert type="info">Pick a start and end date.</Alert>}
      {loading && !data && <Loading />}

      {data && (
        <>
          <section className="card">
            <h2>Users</h2>
            <div className="metrics-grid">
              <Metric label="Total users" value={data.users.total} to="/admin/users" />
              <Metric label="Active (30 days)" value={data.users.active} />
              <Metric label="Inactive" value={data.users.inactive} />
              <Metric label="New today" value={data.users.new_today} />
              <Metric label="New this week" value={data.users.new_week} />
              <Metric label="New this month" value={data.users.new_month} />
              <Metric label="Blocked" value={data.users.blocked} to="/admin/users?status=blocked" />
              <Metric label="Admins" value={data.users.admins} />
            </div>
          </section>

          <div className="grid-2">
            <section className="card">
              <h2>Transactions</h2>
              <div className="metrics-grid metrics-grid-3">
                <Metric label="Total" value={data.transactions.total} to="/admin/transactions" />
                <Metric label="Today" value={data.transactions.today} />
                <Metric label="This week" value={data.transactions.week} />
                <Metric label="This month" value={data.transactions.month} />
                <Metric label="Total value" value={formatCurrency(data.transactions.total_value)} />
                <Metric label="Average" value={formatCurrency(data.transactions.average_value)} />
              </div>
            </section>
            <section className="card">
              <h2>Security</h2>
              <div className="metrics-grid metrics-grid-3">
                <Metric label="Login attempts today" value={data.security.login_attempts_today} to="/admin/security" />
                <Metric label="Failed today" value={data.security.failed_logins_today} />
                <Metric label="Successful today" value={data.security.successful_logins_today} />
                <Metric label="Active sessions" value={data.security.active_sessions} to="/admin/sessions" />
                <Metric label="Blocked IPs" value={data.security.blocked_ips} to="/admin/ip-addresses?tab=blocked" />
                <Metric label="Suspicious (range)" value={data.security.suspicious_in_range} to="/admin/security?tab=suspicious" />
              </div>
            </section>
          </div>

          <section className="card">
            <div className="card-header">
              <h2>System</h2>
              <Link to="/admin/system" className="small">Details →</Link>
            </div>
            <div className="health-row">
              {Object.entries(data.system.components).map(([name, c]) => (
                <div key={name} className="health-item">
                  <span className="muted small">{COMPONENT_LABELS[name] || name}</span>
                  <HealthPill status={c.status} />
                </div>
              ))}
              <div className="health-item">
                <span className="muted small">uptime</span>
                <strong>{formatUptime(data.system.uptime_seconds)}</strong>
              </div>
              <div className="health-item">
                <span className="muted small">recent errors</span>
                <strong>{data.system.recent_errors}</strong>
              </div>
            </div>
          </section>

          <div className="grid-2">
            <section className="card">
              <h2>User registrations</h2>
              <ColumnChart data={toChart(data.series.registrations)} tickFormatter={dayLabel} tooltipLabel={dayLabel}
                valueFormatter={(v) => `${v} users`} tableCaption="Registrations per day" />
            </section>
            <section className="card">
              <h2>Active users</h2>
              <p className="muted small">Logged in or added a transaction that day</p>
              <ColumnChart data={toChart(data.series.active_users)} tickFormatter={dayLabel} tooltipLabel={dayLabel}
                valueFormatter={(v) => `${v} users`} tableCaption="Active users per day" />
            </section>
            <section className="card">
              <h2>Transaction volume</h2>
              <ColumnChart data={toChart(data.series.transactions)} tickFormatter={dayLabel} tooltipLabel={dayLabel}
                valueFormatter={(v) => `${v} transactions`} tableCaption="Transactions per day" />
            </section>
            <section className="card">
              <h2>Transaction value</h2>
              <ColumnChart data={toChart(data.series.transaction_value)} tickFormatter={dayLabel} tooltipLabel={dayLabel}
                tableCaption="Transaction value per day" />
            </section>
          </div>

          <div className="grid-2 grid-2-wide">
            <section className="card">
              <h2>Login activity</h2>
              <StackedColumnChart
                data={data.series.logins_success.map((p, i) => ({
                  label: p.date, success: p.value, failed: data.series.logins_failed[i].value,
                }))}
                series={[
                  { key: "success", label: "Successful", color: "var(--series-1)" },
                  { key: "failed", label: "Failed", color: "var(--series-2)" },
                ]}
                tickFormatter={dayLabel}
                tooltipLabel={dayLabel}
                valueFormatter={(v) => String(v)}
                tableCaption="Logins per day"
              />
            </section>
            <section className="card">
              <div className="card-header">
                <h2>Recent admin actions</h2>
                <Link to="/admin/audit-logs" className="small">Audit log →</Link>
              </div>
              {data.recent_admin_actions.length === 0 && <p className="empty">No admin actions yet.</p>}
              <ul className="feed">
                {data.recent_admin_actions.map((a) => (
                  <li key={a.id}>
                    <code>{a.action}</code>
                    <div className="small muted">
                      {a.actor || "system"}{a.target ? ` → ${a.target}` : ""} · {formatDateTime(a.at)}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
