import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import TransactionForm from "../components/TransactionForm";
import { transactionService } from "../services/transactionService";

export default function AddExpensePage() {
  const navigate = useNavigate();
  const [formKey, setFormKey] = useState(0);
  const [addAnother, setAddAnother] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);

  const handleSubmit = async (payload) => {
    const created = await transactionService.create(payload);
    if (addAnother) {
      setLastSaved(created);
      setFormKey((k) => k + 1); // reset the form
    } else {
      navigate(`/transactions/${created.id}`);
    }
  };

  return (
    <div className="page page-narrow">
      <div className="page-header">
        <div>
          <h1>Add expense</h1>
          <p className="muted">Record a cash, card or UPI payment by hand.</p>
        </div>
      </div>

      {lastSaved && (
        <Alert type="success" onClose={() => setLastSaved(null)}>
          Saved {lastSaved.merchant_name}. <Link to={`/transactions/${lastSaved.id}`}>View</Link>
        </Alert>
      )}

      <section className="card">
        <TransactionForm key={formKey} onSubmit={handleSubmit} submitLabel="Add expense" />
        <label className="checkbox">
          <input type="checkbox" checked={addAnother} onChange={(e) => setAddAnother(e.target.checked)} />
          Add another after saving
        </label>
      </section>
    </div>
  );
}
