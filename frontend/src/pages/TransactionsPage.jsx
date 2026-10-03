import { useMemo } from "react";
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

  const { data, loading, error, reload } = useApi(
    () => transactionService.list({ ...filters, page, page_size: PAGE_SIZE }),
    [searchParams.toString()],
  );
  const { data: options } = useApi(() => transactionService.filterOptions(), []);

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
        <Link to="/add-expense" className="btn btn-primary">
          + Add expense
        </Link>
      </div>

      <TransactionFilters
        filters={filters}
        options={options || { categories: meta.categories, banks: [], payment_methods: meta.payment_methods }}
        onChange={updateFilters}
      />

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
              <TransactionTable transactions={data.items} />
              <Pagination page={data.page} pages={data.pages} total={data.total} onChange={goToPage} />
            </div>
          )
        )}
      </section>
    </div>
  );
}
