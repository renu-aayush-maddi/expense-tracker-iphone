import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import Loading from "../components/Loading";
import Pagination from "../components/Pagination";
import TransactionFilters from "../components/TransactionFilters";
import TransactionTable from "../components/TransactionTable";
import { useApi } from "../hooks/useApi";
import { useMeta } from "../hooks/useMeta";
import { transactionService } from "../services/transactionService";

const PAGE_SIZE = 20;

export default function TransactionsPage() {
  const meta = useMeta();
  // Filters live in the URL, so they survive refreshes and can be bookmarked.
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => Object.fromEntries(searchParams.entries()), [searchParams]);
  const page = Number(filters.page) || 1;

  const { data, loading, error, reload, setData } = useApi(
    () => transactionService.list({ ...filters, page, page_size: PAGE_SIZE }),
    [searchParams.toString()],
  );
  const { data: options } = useApi(() => transactionService.filterOptions(), []);
  const [actionError, setActionError] = useState("");

  // One click: Company reimbursable <-> Personal. Updates the row in place.
  const toggleReimbursable = async (transaction) => {
    setActionError("");
    try {
      const updated = await transactionService.setReimbursable(transaction.id, !transaction.is_reimbursable);
      setData((current) => ({ ...current, items: current.items.map((t) => (t.id === updated.id ? updated : t)) }));
    } catch (err) {
      setActionError(err.message);
    }
  };

  const downloadCsv = async () => {
    setActionError("");
    try {
      const { page: _page, sort_by: _sortBy, sort_order: _sortOrder, ...exportFilters } = filters;
      await transactionService.exportCsv(exportFilters, "transactions.csv");
    } catch (err) {
      setActionError(err.message);
    }
  };

  const updateFilters = (next) => {
    const clean = Object.fromEntries(Object.entries(next).filter(([, value]) => value !== "" && value != null));
    delete clean.page; // any filter change goes back to page 1
    setSearchParams(clean);
  };

  const goToPage = (newPage) => {
    setSearchParams({ ...filters, page: String(newPage) });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Transactions</h1>
          <p className="muted">Search, filter and open any transaction.</p>
        </div>
        <div className="page-actions">
          <button type="button" className="btn btn-secondary" onClick={downloadCsv}>
            Download CSV
          </button>
          <Link to="/add-expense" className="btn btn-primary">
            + Add expense
          </Link>
        </div>
      </div>

      <TransactionFilters
        filters={filters}
        options={options || { categories: meta.categories, banks: [], payment_methods: meta.payment_methods }}
        onChange={updateFilters}
      />

      {actionError && (
        <Alert type="error" onClose={() => setActionError("")}>
          {actionError}
        </Alert>
      )}

      {error && (
        <Alert type="error">
          {error.message}{" "}
          <button type="button" className="link-button" onClick={reload}>
            Retry
          </button>
        </Alert>
      )}

      <section className="card">
        {loading && !data ? (
          <Loading />
        ) : (
          data && (
            <div className={loading ? "is-refreshing" : ""}>
              <TransactionTable transactions={data.items} onToggleReimbursable={toggleReimbursable} />
              <Pagination page={data.page} pages={data.pages} total={data.total} onChange={goToPage} />
            </div>
          )
        )}
      </section>
    </div>
  );
}
