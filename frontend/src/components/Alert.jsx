const ICONS = { error: "⚠", success: "✓", info: "ℹ", warning: "!" };

/** Message box. type: "error" | "success" | "info" | "warning" */
export default function Alert({ type = "info", title, children, onClose }) {
  if (!children && !title) return null;
  return (
    <div className={`alert alert-${type}`} role={type === "error" ? "alert" : "status"}>
      <span className="alert-icon" aria-hidden="true">
        {ICONS[type]}
      </span>
      <div className="alert-body">
        {title && <strong>{title}</strong>}
        {children && <div>{children}</div>}
      </div>
      {onClose && (
        <button type="button" className="alert-close" aria-label="Dismiss" onClick={onClose}>
          ×
        </button>
      )}
    </div>
  );
}
