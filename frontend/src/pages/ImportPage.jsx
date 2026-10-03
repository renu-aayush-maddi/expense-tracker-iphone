import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import Loading from "../components/Loading";
import { useApi } from "../hooks/useApi";
import { importService } from "../services/importService";
import { formatCurrency, formatDate, formatDateTime } from "../utils/format";

const EXAMPLE = `Paid to
BLINK COMMERCE PRIVA...

Amount:
₹183

Date:
3 October 2026
1:11 PM

PhonePe Transaction ID:
T2610031311415776289288

Debited from:
XXXXXX096929

UTR:
706226593892

Message:
UPIIntent`;

function ImportResult({ result }) {
  if (result.status === "created") {
    return (
      <Alert type="success" title={result.message}>
        <Link to={`/transactions/${result.transaction.id}`}>Open transaction</Link>
      </Alert>
    );
  }
  if (result.status === "duplicate") {
    return (
      <Alert type="info" title="Transaction already exists">
        This receipt was imported before, so nothing new was saved.{" "}
        {result.existing_transaction_id && <Link to={`/transactions/${result.existing_transaction_id}`}>View it</Link>}
      </Alert>
    );
  }
  return <Alert type="error" title="Couldn't read this receipt">{result.message}</Alert>;
}

export default function ImportPage() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const pending = useApi(() => importService.listPending(), []);

  const handleImport = async (event) => {
    event.preventDefault();
    setError("");
    setResult(null);
    setSubmitting(true);
    try {
      const response = await importService.importPhonePe(text);
      if (response.status === "review_required") {
        navigate(`/imports/${response.review_id}`);
        return;
      }
      setResult(response);
      if (response.status === "created") setText("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page page-narrow">
      <div className="page-header">
        <div>
          <h1>Import PhonePe receipt</h1>
          <p className="muted">
            Usually your iPhone Shortcut does this automatically. You can also paste receipt text here to test the
            parser.
          </p>
        </div>
      </div>

      <section className="card">
        <h2>Imports waiting for review</h2>
        {pending.loading && <Loading />}
        {pending.error && <Alert type="error">{pending.error.message}</Alert>}
        {pending.data && pending.data.length === 0 && <p className="empty">Nothing to review. 🎉</p>}
        {pending.data && pending.data.length > 0 && (
          <ul className="pending-list">
            {pending.data.map((item) => (
              <li key={item.id}>
                <Link to={`/imports/${item.id}`} className="pending-item">
                  <div>
                    <strong>{item.parsed_data.merchant_name || "Unknown merchant"}</strong>
                    <div className="muted small">
                      {item.parsed_data.amount ? formatCurrency(item.parsed_data.amount) : "Amount unclear"} ·{" "}
                      {item.parsed_data.transaction_date ? formatDate(item.parsed_data.transaction_date) : "Date unclear"}
                    </div>
                    <div className="warning-text small">{item.issues[0]}</div>
                  </div>
                  <span className="muted small">{formatDateTime(item.created_at)} →</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>Paste receipt text</h2>
        <form className="form" onSubmit={handleImport}>
          {error && <Alert type="error">{error}</Alert>}
          {result && <ImportResult result={result} />}
          <label className="field">
            <span>OCR text from the PhonePe receipt</span>
            <textarea
              rows={12}
              className="mono"
              maxLength={20000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={EXAMPLE}
              required
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={submitting || !text.trim()}>
              {submitting ? "Importing…" : "Import"}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setText(EXAMPLE)}>
              Use sample receipt
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
