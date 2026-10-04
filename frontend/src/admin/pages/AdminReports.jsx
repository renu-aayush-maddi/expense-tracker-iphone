import { useState } from "react";
import Alert from "../../components/Alert";
import BarList from "../../components/charts/BarList";
import ColumnChart from "../../components/charts/ColumnChart";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { formatCurrency } from "../../utils/format";
import { adminService, can, PERMS } from "../adminService";
import RangePicker, { rangeParams } from "../components/RangePicker";
import { useToast } from "../components/Toast";
import { EVENT_LABELS } from "./AdminSecurity";

const toChart = (series) => series.map((p) => ({ label: p.date, total: p.value }));
const Metric = ({ label, value }) => (
  <div className="metric"><div className="metric-label">{label}</div><div className="metric-value">{value}</div></div>
);

export default function AdminReports() {
  const { user: me } = useAuth();
  const notify = useToast();
  const [type, setType] = useState("users");
  const [range, setRange] = useState({ range: "30d" });
  const params = rangeParams(range);
  const { data, loading, error } = useApi(() => (params ? adminService.report(type, params) : Promise.resolve(null)),
    [type, JSON.stringify(params)]);

  const exportCsv = async () => {
    try {
      await adminService.exportReport(type, params);
      notify("Report exported (recorded in the audit log)");
    } catch (err) {
      notify(err.message, "error");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Reports</h1>
          <p className="muted">Aggregated figures only. No passwords, tokens or receipt text.</p>
        </div>
        <div className="page-actions">
          <RangePicker value={range} onChange={setRange} />
          {can(me, PERMS.export) && <button type="button" className="btn btn-secondary" onClick={exportCsv} disabled={!params}>Export CSV</button>}
        </div>
      </div>
      <div className="tabs" role="tablist">
        {[["users", "Users"], ["transactions", "Transactions"], ["security", "Security"]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={type === key} className={type === key ? "is-active" : ""}
            onClick={() => setType(key)}>{label}</button>
        ))}
      </div>
      {error && <Alert type="error">{error.message}</Alert>}
      {loading && !data && <Loading />}

      {data && type === "users" && data.by_role && (
        <>
          <div className="metrics-grid">
            <Metric label="New users" value={data.new_users} />
            <Metric label="Active in range" value={data.active_users} />
            <Metric label="Inactive" value={data.inactive_users} />
            <Metric label="Blocked" value={data.blocked_users} />
          </div>
          <div className="grid-2 grid-2-wide">
            <section className="card"><h2>Registrations</h2>
              <ColumnChart data={toChart(data.registrations)} valueFormatter={(v) => `${v} users`} tableCaption="Registrations" /></section>
            <section className="card"><h2>By status</h2>
              <ul className="kv-list">{Object.entries(data.by_status).map(([k, v]) => <li key={k}><span>{k}</span><strong>{v}</strong></li>)}</ul>
              <h2>By role</h2>
              <ul className="kv-list">{Object.entries(data.by_role).map(([k, v]) => <li key={k}><span>{k}</span><strong>{v}</strong></li>)}</ul>
            </section>
          </div>
        </>
      )}

      {data && type === "transactions" && data.by_category && (
        <>
          <div className="metrics-grid">
            <Metric label="Transactions" value={data.transaction_count} />
            <Metric label="Total spending" value={formatCurrency(data.total_spending)} />
            <Metric label="Average" value={formatCurrency(data.average_spending)} />
          </div>
          <div className="grid-2">
            <section className="card"><h2>By category</h2><BarList items={data.by_category} /></section>
            <section className="card"><h2>Top merchants</h2><BarList items={data.by_merchant} /></section>
          </div>
        </>
      )}

      {data && type === "security" && data.top_failing_ips && (
        <>
          <div className="metrics-grid">
            <Metric label="Login attempts" value={data.login_attempts} />
            <Metric label="Successful" value={data.successful_logins} />
            <Metric label="Failed" value={data.failed_logins} />
            <Metric label="Blocked logins" value={data.blocked_logins} />
            <Metric label="Requests from blocked IPs" value={data.blocked_ip_requests} />
            <Metric label="IPs blocked in range" value={data.ips_blocked_in_range} />
            <Metric label="Active IP blocks" value={data.active_ip_blocks} />
          </div>
          <div className="grid-2">
            <section className="card"><h2>Failed logins per day</h2>
              <ColumnChart data={toChart(data.logins_failed)} valueFormatter={(v) => `${v} failed`} tableCaption="Failed logins" /></section>
            <section className="card">
              <h2>Suspicious events</h2>
              {Object.keys(data.suspicious_events).length === 0 ? <p className="empty">None in this range.</p> : (
                <ul className="kv-list">{Object.entries(data.suspicious_events).map(([k, v]) => (
                  <li key={k}><span>{EVENT_LABELS[k] || k}</span><strong>{v}</strong></li>))}</ul>
              )}
              <h2>Top failing IPs</h2>
              {data.top_failing_ips.length === 0 ? <p className="empty">None.</p> : (
                <ul className="kv-list">{data.top_failing_ips.map((r) => (
                  <li key={r.ip_address}><span className="mono">{r.ip_address}</span><strong>{r.failed_logins}</strong></li>))}</ul>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
