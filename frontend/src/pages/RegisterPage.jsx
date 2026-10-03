import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import { useAuth } from "../hooks/useAuth";
import { useMeta } from "../hooks/useMeta";

export default function RegisterPage() {
  const { register } = useAuth();
  const meta = useMeta();
  const navigate = useNavigate();
  const [form, setForm] = useState({ fullName: "", email: "", password: "", confirm: "" });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    if (form.password.length < 8) return setError("Password must be at least 8 characters.");
    if (form.password !== form.confirm) return setError("Passwords don't match.");
    setSubmitting(true);
    try {
      await register(form.email.trim(), form.password, form.fullName.trim());
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (!meta.allow_registration) {
    return (
      <div className="auth-page">
        <div className="card auth-card">
          <h1>Registration is closed</h1>
          <p className="muted">This is a personal app and new accounts are disabled.</p>
          <Link to="/login" className="btn btn-primary btn-block">
            Go to login
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <form className="card auth-card" onSubmit={handleSubmit}>
        <div className="auth-brand">
          <span className="brand-mark">₹</span>
          <h1>Create account</h1>
        </div>
        {error && <Alert type="error">{error}</Alert>}
        <label className="field">
          <span>Name (optional)</span>
          <input type="text" autoComplete="name" value={form.fullName} onChange={set("fullName")} />
        </label>
        <label className="field">
          <span>Email</span>
          <input type="email" autoComplete="email" required value={form.email} onChange={set("email")} />
        </label>
        <label className="field">
          <span>Password (min. 8 characters)</span>
          <input type="password" autoComplete="new-password" required value={form.password} onChange={set("password")} />
        </label>
        <label className="field">
          <span>Confirm password</span>
          <input type="password" autoComplete="new-password" required value={form.confirm} onChange={set("confirm")} />
        </label>
        <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>
        <p className="muted small center">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </form>
    </div>
  );
}
