import { useEffect, useState } from "react";
import { setCachedRule } from "../hooks/useReimbursementRule";
import { settingsService } from "../services/settingsService";
import { WEEKDAYS } from "../utils/reimbursement";
import Alert from "./Alert";
import Loading from "./Loading";

/** Settings card for the company-reimbursement rule. */
export default function ReimbursementSettings() {
  const [rule, setRule] = useState(null);
  const [keywordsText, setKeywordsText] = useState("");
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    settingsService
      .getReimbursementRule()
      .then((data) => {
        setRule(data);
        setKeywordsText(data.keywords.join(", "));
      })
      .catch((err) => setError(err.message));
  }, []);

  const toggleDay = (day) =>
    setRule((current) => ({
      ...current,
      weekdays: current.weekdays.includes(day) ? current.weekdays.filter((d) => d !== day) : [...current.weekdays, day],
    }));

  const save = async (event) => {
    event.preventDefault();
    setError("");
    setMessage("");
    setSaving(true);
    try {
      const keywords = keywordsText.split(",").map((k) => k.trim()).filter(Boolean);
      const saved = await settingsService.saveReimbursementRule({ ...rule, keywords });
      setRule(saved);
      setKeywordsText(saved.keywords.join(", "));
      setCachedRule(saved);
      setMessage("Saved. New transactions will use this rule. To update past ones, click “Apply to existing transactions”.");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const apply = async () => {
    setError("");
    setMessage("");
    setApplying(true);
    try {
      const { updated } = await settingsService.applyReimbursementRule();
      setMessage(`Done: ${updated} transaction${updated === 1 ? "" : "s"} updated. Transactions you set by hand were not changed.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setApplying(false);
    }
  };

  return (
    <section className="card">
      <h2>Company reimbursement</h2>
      <p className="muted">
        Transactions matching this rule are marked <strong>Company</strong> automatically. You can always flip any
        transaction with its Company / Personal button; your choice is never overwritten by the rule.
      </p>
      {error && <Alert type="error">{error}</Alert>}
      {message && (
        <Alert type="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      {!rule && !error && <Loading />}
      {rule && (
        <form className="form" onSubmit={save}>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={rule.enabled}
              onChange={(e) => setRule({ ...rule, enabled: e.target.checked })}
            />
            Automatically mark matching transactions as company reimbursable
          </label>

          <label className="field">
            <span>Merchant names to match (comma separated)</span>
            <input
              type="text"
              value={keywordsText}
              onChange={(e) => setKeywordsText(e.target.value)}
              disabled={!rule.enabled}
              placeholder="uber, ola, rapido"
            />
            <span className="muted small">
              Whole words, any capitalisation. Defaults include “ani technologies” (Ola) and “roppen” (Rapido), the
              company names UPI receipts often show.
            </span>
          </label>

          <fieldset className="field weekday-picker" disabled={!rule.enabled}>
            <span>On these days</span>
            <div className="weekday-row">
              {WEEKDAYS.map((name, day) => (
                <label key={name} className={`weekday ${rule.weekdays.includes(day) ? "is-on" : ""}`}>
                  <input type="checkbox" checked={rule.weekdays.includes(day)} onChange={() => toggleDay(day)} />
                  {name}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving…" : "Save rule"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={apply} disabled={applying}>
              {applying ? "Applying…" : "Apply to existing transactions"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
