import { useState } from "react";
import Alert from "../components/Alert";
import { useAuth } from "../hooks/useAuth";

/** Change your password. `forced` = shown full-screen after an admin reset. */
export default function ChangePasswordPage({ forced = false }) {
  const { changePassword, logout } = useAuth();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setDone(false);
    if (form.next.length < 8) return setError("The new password must be at least 8 characters.");
    if (form.next !== form.confirm) return setError("The new passwords don't match.");
    setSaving(true);
    try {
      await changePassword(form.current, form.next);
      setForm({ current: "", next: "", confirm: "" });
      setDone(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const formBody = (
    <form className="form" onSubmit={submit}>
      {error && <Alert type="error">{error}</Alert>}
      {done && <Alert type="success">Password changed. Your other devices were logged out.</Alert>}
      <label className="field">
        <span>{forced ? "Temporary password" : "Current password"}</span>
        <input type="password" autoComplete="current-password" required value={form.current} onChange={set("current")} />
      </label>
      <label className="field">
        <span>New password (min. 8 characters)</span>
        <input type="password" autoComplete="new-password" required value={form.next} onChange={set("next")} />
      </label>
      <label className="field">
        <span>Repeat new password</span>
        <input type="password" autoComplete="new-password" required value={form.confirm} onChange={set("confirm")} />
      </label>
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Saving…" : "Change password"}</button>
        {forced && <button type="button" className="btn btn-ghost" onClick={logout}>Log out</button>}
      </div>
    </form>
  );

  if (!forced) return formBody;
  return (
    <div className="auth-page">
      <div className="card auth-card">
        <div className="auth-brand">
          <span className="brand-mark">₹</span>
          <h1>Choose a new password</h1>
        </div>
        <p className="muted">An administrator reset your password. Pick a new one to continue.</p>
        {formBody}
      </div>
    </div>
  );
}
