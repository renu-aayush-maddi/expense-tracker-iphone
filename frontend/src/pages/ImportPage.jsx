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

const SOURCE_TEXT = {
  ocr: "Read by server OCR.",
  openai_fallback: "Read with the AI vision fallback (OCR wasn't sure).",
  text: "Read from pasted text.",
};
const MAX_UPLOAD_MB = 10;

function ImportResult({ result }) {
  if (result.status === "created") {
    return (
      <Alert type="success" title={result.message}>
        {SOURCE_TEXT[result.extraction_source] && <span>{SOURCE_TEXT[result.extraction_source]} </span>}
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
  const [retrying, setRetrying] = useState(false);
  const [retryResult, setRetryResult] = useState("");
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [uploadError, setUploadError] = useState("");

  // Upload the original receipt image: the server runs OCR (and the AI fallback if needed).
  const handleUpload = async (event) => {
    event.preventDefault();
    setUploadError("");
    setUploadResult(null);
    if (!file) return;
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setUploadError(`The image is larger than ${MAX_UPLOAD_MB} MB.`);
      return;
    }
    setUploading(true);
    try {
      const response = await importService.importPhonePeImage(file);
      if (response.status === "review_required") {
        navigate(`/imports/${response.review_id}`);
        return;
      }
      setUploadResult(response);
      if (response.status === "created") setFile(null);
      pending.reload();
    } catch (err) {
      setUploadError(err.message);
    } finally {
      setUploading(false);
    }
  };

  // Re-run every pending import through the latest parser (+ AI fallback).
  const handleRetryAll = async () => {
    setRetrying(true);
    setRetryResult("");
    setError("");
    try {
      const counts = await importService.reprocessPending();
      const parts = [];
      if (counts.created) parts.push(`${counts.created} saved`);
      if (counts.duplicate) parts.push(`${counts.duplicate} already existed`);
      if (counts.review_required) parts.push(`${counts.review_required} still need review`);
      setRetryResult(parts.length ? parts.join(", ") + "." : "Nothing changed.");
      pending.reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setRetrying(false);
    }
  };

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
        <div className="card-header">
          <h2>Imports waiting for review</h2>
          {pending.data?.length > 0 && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={handleRetryAll} disabled={retrying}>
              {retrying ? "Retrying…" : "Retry all"}
            </button>
          )}
        </div>
        {retryResult && (
          <Alert type="success" onClose={() => setRetryResult("")}>
            {retryResult}
          </Alert>
        )}
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
        <h2>Upload receipt image</h2>
        <p className="muted small">
          The original PhonePe receipt (JPEG, PNG or HEIC, up to {MAX_UPLOAD_MB} MB). The server reads it with OCR.
          The AI is only asked when OCR isn't sure, and anything uncertain goes to review.
        </p>
        <form className="form" onSubmit={handleUpload}>
          {uploadError && <Alert type="error">{uploadError}</Alert>}
          {uploadResult && <ImportResult result={uploadResult} />}
          <label className="field">
            <span>Receipt image</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/heic,image/heif,.heic,.heif"
              onChange={(e) => {
                setFile(e.target.files?.[0] || null);
                setUploadResult(null);
              }}
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={!file || uploading}>
              {uploading ? "Reading receipt…" : "Upload & import"}
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <h2>Paste receipt text (legacy)</h2>
        <p className="muted small">For text already extracted on the phone. Image upload is more reliable.</p>
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
