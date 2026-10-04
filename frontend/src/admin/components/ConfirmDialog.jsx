import { useEffect, useRef, useState } from "react";
import Alert from "../../components/Alert";

/**
 * Confirmation step for sensitive actions.
 *   requireReason   – the admin must explain why (stored in the audit log)
 *   requirePassword – the admin re-enters their own password (re-authentication)
 *   confirmText     – for destructive actions, the admin must type this word
 * onConfirm({ reason, password }) may throw an ApiError; its message is shown in the dialog.
 */
export default function ConfirmDialog({
  open,
  title,
  children,
  consequences,
  actionLabel = "Confirm",
  danger = false,
  requireReason = false,
  reasonOptional = false,
  requirePassword = false,
  confirmText,
  onConfirm,
  onClose,
}) {
  const [reason, setReason] = useState("");
  const [password, setPassword] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    setReason("");
    setPassword("");
    setTyped("");
    setError("");
    const onKey = (event) => event.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    dialogRef.current?.querySelector("textarea, input, button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  const reasonOk = !requireReason || reasonOptional || reason.trim().length >= 3;
  const ready = reasonOk && (!requirePassword || password) && (!confirmText || typed === confirmText);

  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError("");
    try {
      await onConfirm({ reason: reason.trim() || undefined, password: password || undefined });
      onClose();
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <form className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title" ref={dialogRef} onSubmit={submit}>
        <h2 id="confirm-title">{title}</h2>
        {children && <div className="modal-body">{children}</div>}
        {consequences && <Alert type={danger ? "warning" : "info"}>{consequences}</Alert>}
        {error && <Alert type="error">{error}</Alert>}

        {requireReason && (
          <label className="field">
            <span>Reason{reasonOptional ? " (optional)" : ""}</span>
            <textarea rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="Recorded in the audit log" />
          </label>
        )}
        {confirmText && (
          <label className="field">
            <span>
              Type <strong>{confirmText}</strong> to confirm
            </span>
            <input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </label>
        )}
        {requirePassword && (
          <label className="field">
            <span>Your password (required for this action)</span>
            <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
        )}

        <div className="modal-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className={`btn ${danger ? "btn-danger-solid" : "btn-primary"}`} disabled={!ready || busy}>
            {busy ? "Working…" : actionLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
