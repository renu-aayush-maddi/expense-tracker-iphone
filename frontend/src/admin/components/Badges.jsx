import { ROLE_LABELS } from "../adminService";

const STATUS_ICONS = { active: "●", blocked: "⛔", disabled: "○", suspended: "⏸", deleted: "✕" };

/** Status uses an icon + label, never colour alone. */
export function StatusBadge({ status }) {
  return (
    <span className={`status-badge status-${status}`}>
      <span aria-hidden="true">{STATUS_ICONS[status] || "•"}</span> {status}
    </span>
  );
}

export function RoleBadge({ role }) {
  return <span className={`role-badge role-${role}`}>{ROLE_LABELS[role] || role}</span>;
}

export function SeverityBadge({ severity }) {
  const icon = { info: "ℹ", warning: "!", critical: "‼" }[severity] || "•";
  return (
    <span className={`severity severity-${severity}`}>
      <span aria-hidden="true">{icon}</span> {severity}
    </span>
  );
}

export function ResultBadge({ ok }) {
  if (ok === null || ok === undefined) return <span className="muted">—</span>;
  return <span className={ok ? "result-ok" : "result-fail"}>{ok ? "✓ success" : "✕ failed"}</span>;
}

export const shortId = (id) => (id ? `${String(id).slice(0, 8)}…` : "—");
