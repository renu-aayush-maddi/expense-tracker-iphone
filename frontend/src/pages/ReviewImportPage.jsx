import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Alert from "../components/Alert";
import Loading from "../components/Loading";
import TransactionForm from "../components/TransactionForm";
import { useApi } from "../hooks/useApi";
import { importService } from "../services/importService";
import { formatDateTime } from "../utils/format";

// Which form fields to highlight for each kind of parser issue.
function fieldsToHighlight(issues) {
  const text = issues.join(" ").toLowerCase();
  const fields = [];
  if (text.includes("amount")) fields.push("amount");
  if (text.includes("merchant")) fields.push("merchant_name");
  if (text.includes("date")) fields.push("transaction_date");
  if (text.includes("transaction id") || text.includes("utr")) fields.push("phonepe_transaction_id", "utr");
  return fields;
}

export default function ReviewImportPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: pending, loading, error } = useApi(() => importService.getPending(id), [id]);
  const [conflict, setConflict] = useState(null); // { message, existingId, similar, payload }
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState("");

  const save = async (payload, allowSimilar = false) => {
    try {
      const created = await importService.confirmPending(id, payload, allowSimilar);
      navigate(`/transactions/${created.id}`, { replace: true });
    } catch (err) {
      if (err.status === 409) {
        setConflict({
          message: err.message,
          existingId: err.data?.detail?.existing_transaction_id,
          similar: Boolean(err.data?.detail?.similar),
          payload,
        });
        return;
      }
      throw err; // shown inside the form
    }
  };

  const saveAnyway = async () => {
    setSaving(true);
    setActionError("");
    try {
      await save(conflict.payload, true);
    } catch (err) {
      setActionError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const discard = async () => {
    if (!window.confirm("Discard this import? Nothing will be saved.")) return;
    try {
      await importService.discardPending(id);
      navigate("/import", { replace: true });
    } catch (err) {
      setActionError(err.message);
    }
  };

  if (loading) return <Loading />;
  if (error) {
    return (
      <div className="page page-narrow">
        <Alert type="error">
          {error.status === 404 ? "This import was already reviewed or discarded." : error.message}
        </Alert>
        <Link to="/import">← Back to imports</Link>
      </div>
    );
  }

  const parsed = pending.parsed_data;
  const initialValues = {
    ...parsed,
    payment_method: parsed.payment_method || "UPI",
    category: parsed.category || "Other",
    notes: parsed.message && !/^upi\s*intent$/i.test(parsed.message) ? parsed.message : "",
  };

  return (
    <div className="page page-narrow">
      <Link to="/import" className="back-link">
        ← Imports
      </Link>
      <div className="page-header">
        <div>
          <h1>Review PhonePe import</h1>
          <p className="muted">Received {formatDateTime(pending.created_at)}. Check the details, fix anything wrong, then save.</p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={discard}>
          Discard
        </button>
      </div>

      <Alert type="warning" title="Why this needs review">
        <ul className="issue-list">
          {pending.issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      </Alert>
      {parsed.warnings?.length > 0 && (
        <Alert type="info" title="Also noticed">
          <ul className="issue-list">
            {parsed.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Alert>
      )}

      {actionError && <Alert type="error">{actionError}</Alert>}

      {conflict && (
        <Alert type="error" title={conflict.similar ? "Possible duplicate" : "Already saved"}>
          <p>{conflict.message}</p>
          <div className="form-actions">
            {conflict.existingId && (
              <Link to={`/transactions/${conflict.existingId}`} className="btn btn-secondary btn-sm">
                View existing
              </Link>
            )}
            {conflict.similar ? (
              <button type="button" className="btn btn-primary btn-sm" onClick={saveAnyway} disabled={saving}>
                {saving ? "Saving…" : "It's a different payment, save anyway"}
              </button>
            ) : (
              <button type="button" className="btn btn-secondary btn-sm" onClick={discard}>
                Discard this import
              </button>
            )}
          </div>
        </Alert>
      )}

      <section className="card">
        <TransactionForm
          initialValues={initialValues}
          onSubmit={(payload) => {
            setConflict(null);
            return save(payload);
          }}
          submitLabel="Save transaction"
          showIdentifiers
          highlight={fieldsToHighlight(pending.issues)}
        />
      </section>

      <details className="card debug">
        <summary>Raw OCR text</summary>
        <pre>{pending.raw_text}</pre>
      </details>
    </div>
  );
}
