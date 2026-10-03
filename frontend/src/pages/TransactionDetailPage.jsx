import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Alert from "../components/Alert";
import Loading from "../components/Loading";
import SourceBadge from "../components/SourceBadge";
import TransactionForm from "../components/TransactionForm";
import { useApi } from "../hooks/useApi";
import { transactionService } from "../services/transactionService";
import { formatCurrency, formatDate, formatDateTime, formatTime } from "../utils/format";

function Detail({ label, value, mono = false }) {
  return (
    <div className="detail">
      <dt>{label}</dt>
      <dd className={mono ? "mono" : ""}>{value || "—"}</dd>
    </div>
  );
}

export default function TransactionDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: t, loading, error, setData } = useApi(() => transactionService.get(id), [id]);
  const [editing, setEditing] = useState(false);
  const [message, setMessage] = useState("");
  const [actionError, setActionError] = useState("");

  const handleSave = async (payload) => {
    const updated = await transactionService.update(id, payload);
    setData(updated);
    setEditing(false);
    setMessage("Transaction updated.");
  };

  const handleDelete = async () => {
    if (!window.confirm(`Delete ${t.merchant_name} (${formatCurrency(t.amount)})? This cannot be undone.`)) return;
    try {
      await transactionService.remove(id);
      navigate("/transactions", { replace: true });
    } catch (err) {
      setActionError(err.message);
    }
  };

  if (loading) return <Loading />;
  if (error) {
    return (
      <div className="page">
        <Alert type="error">{error.status === 404 ? "This transaction doesn't exist." : error.message}</Alert>
        <Link to="/transactions">← Back to transactions</Link>
      </div>
    );
  }

  return (
    <div className="page page-narrow">
      <Link to="/transactions" className="back-link">
        ← Transactions
      </Link>

      <div className="page-header">
        <div>
          <h1 className="amount-hero">{formatCurrency(t.amount)}</h1>
          <p className="detail-merchant">
            {t.merchant_name} <SourceBadge source={t.source} />
          </p>
        </div>
        {!editing && (
          <div className="page-actions">
            <button type="button" className="btn btn-secondary" onClick={() => { setEditing(true); setMessage(""); }}>
              Edit
            </button>
            <button type="button" className="btn btn-danger" onClick={handleDelete}>
              Delete
            </button>
          </div>
        )}
      </div>

      {message && <Alert type="success" onClose={() => setMessage("")}>{message}</Alert>}
      {actionError && <Alert type="error">{actionError}</Alert>}

      {editing ? (
        <section className="card">
          <h2>Edit transaction</h2>
          <TransactionForm
            initialValues={t}
            onSubmit={handleSave}
            onCancel={() => setEditing(false)}
            submitLabel="Save changes"
            showIdentifiers={t.source !== "manual"}
          />
        </section>
      ) : (
        <>
          <section className="card">
            <dl className="details-grid">
              <Detail label="Amount" value={formatCurrency(t.amount)} />
              <Detail label="Merchant" value={t.merchant_name} />
              <Detail label="Category" value={t.category} />
              <Detail label="Date" value={formatDate(t.transaction_date)} />
              <Detail label="Time" value={t.transaction_time && formatTime(t.transaction_time)} />
              <Detail label="Payment method" value={t.payment_method} />
              <Detail label="Bank" value={t.bank} />
              <Detail label="Account last 4" value={t.account_last4 && `•••• ${t.account_last4}`} />
              <Detail label="PhonePe transaction ID" value={t.phonepe_transaction_id} mono />
              <Detail label="UTR" value={t.utr} mono />
              {t.upi_reference && t.upi_reference !== t.utr && <Detail label="UPI reference" value={t.upi_reference} mono />}
              <Detail label="Source" value={<SourceBadge source={t.source} />} />
              <Detail label="Created" value={formatDateTime(t.created_at)} />
              {t.updated_at !== t.created_at && <Detail label="Last updated" value={formatDateTime(t.updated_at)} />}
            </dl>
            {t.notes && (
              <div className="notes">
                <h3>Notes</h3>
                <p>{t.notes}</p>
              </div>
            )}
          </section>

          {t.raw_ocr_text && (
            <details className="card debug">
              <summary>Debug details: raw OCR text</summary>
              <p className="muted small">The exact text your iPhone extracted from the receipt image.</p>
              <pre>{t.raw_ocr_text}</pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}
