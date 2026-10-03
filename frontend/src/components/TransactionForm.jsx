import { useEffect, useState } from "react";
import { useMeta } from "../hooks/useMeta";
import { transactionService } from "../services/transactionService";
import { todayISO } from "../utils/format";
import Alert from "./Alert";

const COMMON_BANKS = ["HDFC", "ICICI", "SBI", "Kotak", "Axis", "Yes Bank", "IDFC First", "IndusInd", "PNB", "Bank of Baroda"];

const EMPTY = {
  amount: "",
  merchant_name: "",
  category: "Other",
  transaction_date: "",
  transaction_time: "",
  payment_method: "UPI",
  bank: "",
  notes: "",
  phonepe_transaction_id: "",
  utr: "",
  upi_reference: "",
  account_last4: "",
};

/** Convert API data (nulls, "13:11:00") into form values ("", "13:11"). */
export function toFormValues(data = {}) {
  const values = { ...EMPTY, transaction_date: todayISO() };
  Object.keys(EMPTY).forEach((key) => {
    if (data[key] !== null && data[key] !== undefined) values[key] = String(data[key]);
  });
  if (values.transaction_time) values.transaction_time = values.transaction_time.slice(0, 5);
  if (values.amount) values.amount = String(Number(values.amount));
  return values;
}

/** Convert form values into the JSON the API expects (empty -> null). */
function toPayload(values) {
  const payload = {};
  Object.entries(values).forEach(([key, value]) => {
    const trimmed = typeof value === "string" ? value.trim() : value;
    payload[key] = trimmed === "" ? null : trimmed;
  });
  return payload;
}

function validate(values) {
  const errors = {};
  const amount = Number(values.amount);
  if (!values.amount || Number.isNaN(amount) || amount <= 0) errors.amount = "Enter an amount greater than 0.";
  else if (!/^\d+(\.\d{1,2})?$/.test(values.amount.trim())) errors.amount = "Use at most 2 decimal places.";
  if (!values.merchant_name.trim()) errors.merchant_name = "Merchant is required.";
  if (!values.transaction_date) errors.transaction_date = "Date is required.";
  if (values.account_last4 && !/^\d{4}$/.test(values.account_last4.trim()))
    errors.account_last4 = "Must be exactly 4 digits.";
  return errors;
}

/**
 * Shared form for: add expense, edit transaction, and review PhonePe import.
 * `onSubmit(payload)` should throw an ApiError on failure.
 */
export default function TransactionForm({
  initialValues,
  onSubmit,
  submitLabel = "Save",
  onCancel,
  showIdentifiers = false,
  highlight = [],
}) {
  const meta = useMeta();
  const [values, setValues] = useState(() => toFormValues(initialValues));
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [banks, setBanks] = useState(COMMON_BANKS);

  useEffect(() => {
    transactionService
      .filterOptions()
      .then((options) => setBanks([...new Set([...options.banks, ...COMMON_BANKS])]))
      .catch(() => {});
  }, []);

  const set = (field) => (event) => {
    setValues((current) => ({ ...current, [field]: event.target.value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setFormError("");
    const clientErrors = validate(values);
    setErrors(clientErrors);
    if (Object.keys(clientErrors).length) return;

    setSaving(true);
    try {
      await onSubmit(toPayload(values));
    } catch (error) {
      // Map server-side validation errors onto fields where possible.
      const serverErrors = {};
      (error?.data?.errors || []).forEach((e) => {
        if (e.field in EMPTY) serverErrors[e.field] = e.message;
      });
      setErrors(serverErrors);
      setFormError(error.message || "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  const fieldClass = (name) => `field ${highlight.includes(name) ? "field-highlight" : ""}`;
  const error = (name) => errors[name] && <span className="field-error">{errors[name]}</span>;

  return (
    <form className="form" onSubmit={handleSubmit} noValidate>
      {formError && <Alert type="error">{formError}</Alert>}

      <div className="form-grid">
        <label className={fieldClass("amount")}>
          <span>Amount (₹) *</span>
          <input
            type="text"
            inputMode="decimal"
            placeholder="e.g. 500"
            value={values.amount}
            onChange={set("amount")}
            aria-invalid={Boolean(errors.amount)}
            autoFocus={!initialValues}
          />
          {error("amount")}
        </label>

        <label className={fieldClass("merchant_name")}>
          <span>Merchant *</span>
          <input
            type="text"
            placeholder="e.g. Zomato"
            maxLength={255}
            value={values.merchant_name}
            onChange={set("merchant_name")}
            aria-invalid={Boolean(errors.merchant_name)}
          />
          {error("merchant_name")}
        </label>

        <label className={fieldClass("category")}>
          <span>Category</span>
          <select value={values.category} onChange={set("category")}>
            {meta.categories.map((category) => (
              <option key={category}>{category}</option>
            ))}
          </select>
        </label>

        <label className={fieldClass("payment_method")}>
          <span>Payment method</span>
          <select value={values.payment_method} onChange={set("payment_method")}>
            <option value="">—</option>
            {meta.payment_methods.map((method) => (
              <option key={method}>{method}</option>
            ))}
          </select>
        </label>

        <label className={fieldClass("transaction_date")}>
          <span>Date *</span>
          <input
            type="date"
            value={values.transaction_date}
            onChange={set("transaction_date")}
            aria-invalid={Boolean(errors.transaction_date)}
          />
          {error("transaction_date")}
        </label>

        <label className={fieldClass("transaction_time")}>
          <span>Time</span>
          <input type="time" value={values.transaction_time} onChange={set("transaction_time")} />
        </label>

        <label className={fieldClass("bank")}>
          <span>Bank</span>
          <input type="text" list="bank-options" placeholder="e.g. Kotak" maxLength={100} value={values.bank} onChange={set("bank")} />
          <datalist id="bank-options">
            {banks.map((bank) => (
              <option key={bank} value={bank} />
            ))}
          </datalist>
        </label>

        <label className={fieldClass("account_last4")}>
          <span>Account last 4 digits</span>
          <input
            type="text"
            inputMode="numeric"
            maxLength={4}
            placeholder="6929"
            value={values.account_last4}
            onChange={set("account_last4")}
            aria-invalid={Boolean(errors.account_last4)}
          />
          {error("account_last4")}
        </label>

        <label className={`${fieldClass("notes")} span-2`}>
          <span>Notes</span>
          <textarea rows={2} maxLength={2000} placeholder="e.g. Dinner" value={values.notes} onChange={set("notes")} />
        </label>
      </div>

      <details className="form-section" open={showIdentifiers}>
        <summary>Payment references (PhonePe transaction ID, UTR)</summary>
        <div className="form-grid">
          <label className={fieldClass("phonepe_transaction_id")}>
            <span>PhonePe transaction ID</span>
            <input type="text" maxLength={64} value={values.phonepe_transaction_id} onChange={set("phonepe_transaction_id")} />
            {error("phonepe_transaction_id")}
          </label>
          <label className={fieldClass("utr")}>
            <span>UTR</span>
            <input type="text" maxLength={64} value={values.utr} onChange={set("utr")} />
            {error("utr")}
          </label>
          <label className={fieldClass("upi_reference")}>
            <span>UPI reference</span>
            <input type="text" maxLength={64} value={values.upi_reference} onChange={set("upi_reference")} />
          </label>
        </div>
      </details>

      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving ? "Saving…" : submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
