import Alert from "../../components/Alert";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { formatDateTime } from "../../utils/format";
import { adminService } from "../adminService";
import { formatUptime, HealthPill } from "./AdminDashboard";

import { COMPONENT_LABELS } from "./AdminDashboard";

export default function AdminSystem() {
  const { data, loading, error, reload } = useApi(() => adminService.systemHealth(), []);
  if (loading && !data) return <Loading />;
  if (error) return <Alert type="error">{error.message}</Alert>;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>System health</h1>
          <p className="muted">Live checks. Counters reset when the server restarts. No secrets or environment values are shown.</p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={reload} disabled={loading}>{loading ? "Checking…" : "Re-check"}</button>
      </div>

      <section className="card">
        <div className="card-header">
          <h2>Overall</h2>
          <HealthPill status={data.status} />
        </div>
        <table className="table">
          <thead><tr><th>Component</th><th>Status</th><th className="num">Latency</th><th>Detail</th></tr></thead>
          <tbody>
            {Object.entries(data.components).map(([key, c]) => (
              <tr key={key}>
                <td>{COMPONENT_LABELS[key] || key}</td>
                <td><HealthPill status={c.status} /></td>
                <td className="num">{c.latency_ms} ms</td>
                <td className="small muted">{c.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="metrics-grid">
        <div className="metric"><div className="metric-label">Uptime</div><div className="metric-value">{formatUptime(data.uptime_seconds)}</div>
          <div className="metric-hint">since {formatDateTime(data.started_at)}</div></div>
        <div className="metric"><div className="metric-label">Requests</div><div className="metric-value">{data.requests}</div></div>
        <div className="metric"><div className="metric-label">Server errors</div><div className="metric-value">{data.server_errors}</div>
          <div className="metric-hint">{(data.error_rate * 100).toFixed(2)}% error rate</div></div>
        <div className="metric"><div className="metric-label">Client errors (4xx)</div><div className="metric-value">{data.client_errors}</div></div>
        <div className="metric"><div className="metric-label">Environment</div><div className="metric-value metric-text">{data.environment}</div></div>
        <div className="metric"><div className="metric-label">Version</div><div className="metric-value metric-text">{data.version}</div>
          <div className="metric-hint">build {data.build} · Python {data.python}</div></div>
        <div className="metric"><div className="metric-label">AI receipt fallback</div><div className="metric-value metric-text">{data.ai_fallback}</div></div>
        <div className="metric"><div className="metric-label">Blocked IPs</div><div className="metric-value">{data.blocked_ips}</div></div>
      </div>

      <div className="grid-2">
        <section className="card">
          <h2>Recent application errors</h2>
          <p className="muted small">Error type and path only. Details are in the server logs.</p>
          {data.recent_errors.length === 0 ? <p className="empty">No errors since the last restart. 🎉</p> : (
            <table className="table">
              <tbody>
                {data.recent_errors.map((e, i) => (
                  <tr key={i}>
                    <td className="small nowrap">{formatDateTime(e.at)}</td>
                    <td className="mono small">{e.method} {e.path}</td>
                    <td className="small">{e.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section className="card">
          <h2>Your request (IP detection check)</h2>
          <p className="muted small">After deploying, compare this with your real public IP. If they differ, review CLIENT_IP_HEADERS.</p>
          <dl className="details-grid">
            <div className="detail"><dt>Detected IP</dt><dd className="mono">{data.your_request.detected_ip}</dd></div>
            <div className="detail"><dt>Taken from</dt><dd>{data.your_request.ip_source}</dd></div>
            <div className="detail"><dt>X-Forwarded-For entries</dt><dd>{data.your_request.x_forwarded_for_entries} (not trusted)</dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}
