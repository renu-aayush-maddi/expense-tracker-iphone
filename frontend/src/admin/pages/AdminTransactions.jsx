import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Alert from "../../components/Alert";
import Loading from "../../components/Loading";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { useMeta } from "../../hooks/useMeta";
import { formatCurrency, formatDate, formatDateTime } from "../../utils/format";
import { adminService, can, PERMS } from "../adminService";
import { clean, PagedFooter, SortHeader } from "../components/AdminTable";
import { shortId } from "../components/Badges";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";

export default function AdminTransactions() {
  const { user: me } = useAuth();
  const meta = useMeta();
  const notify = useToast();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const sort = { sort_by: filters.sort_by || "created", sort_order: filters.sort_order || "desc" };
  const { data, loading, error, reload } = useApi(() => adminService.transactions({ page_size: 25, ...filters }), [params.toString()]);
  const [selected, setSelected] = useState(null);
  const [dialog, setDialog] = useState(null);

  const update = (changes, keepPage = false) => {
    const next = clean({ ...filters, ...changes });
    if (!keepPage) delete next.page;
    setParams(next);
  };
  const set = (field) => (e) => update({ [field]: e.target.value });

  const open = async (row) => {
    try {
      setSelected(await adminService.transaction(row.id));
    } catch (err) {
      notify(err.message, "error");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Transactions</h1>
          <p className="muted">All users. Opening a transaction is recorded in the audit log.</p>
        </div>
      </div>
      <div className="card filters">
        <div className="filters-grid">
          <label className="field"><span>User</span>
            <input type="search" placeholder="Email or name" defaultValue={filters.user || ""}
              onKeyDown={(e) => e.key === "Enter" && update({ user: e.target.value })}
              onBlur={(e) => e.target.value !== (filters.user || "") && update({ user: e.target.value })} /></label>
          <label className="field"><span>Merchant</span>
            <input type="search" defaultValue={filters.merchant || ""}
              onKeyDown={(e) => e.key === "Enter" && update({ merchant: e.target.value })}
              onBlur={(e) => e.target.value !== (filters.merchant || "") && update({ merchant: e.target.value })} /></label>
          <label className="field"><span>Category</span>
            <select value={filters.category || ""} onChange={set("category")}>
              <option value="">All</option>
              {meta.categories.map((c) => <option key={c}>{c}</option>)}
            </select></label>
          <label className="field"><span>Source</span>
            <select value={filters.source || ""} onChange={set("source")}>
              <option value="">All</option><option value="manual">Manual</option><option value="phonepe">PhonePe</option>
            </select></label>
          <label className="field"><span>From</span><input type="date" value={filters.date_from || ""} onChange={set("date_from")} /></label>
          <label className="field"><span>To</span><input type="date" value={filters.date_to || ""} onChange={set("date_to")} /></label>
          <label className="field"><span>Min ₹</span><input type="number" min="0" value={filters.min_amount || ""} onChange={set("min_amount")} /></label>
          <label className="field"><span>Max ₹</span><input type="number" min="0" value={filters.max_amount || ""} onChange={set("max_amount")} /></label>
          <label className="field"><span>Deleted</span>
            <select value={filters.deleted || "exclude"} onChange={set("deleted")}>
              <option value="exclude">Hide deleted</option><option value="include">Include deleted</option><option value="only">Only deleted</option>
            </select></label>
        </div>
      </div>

      {error && <Alert type="error">{error.message}</Alert>}
      <section className="card">
        {loading && !data ? <Loading /> : data && (
          <div className={loading ? "is-refreshing" : ""}>
            <div className="table-wrap">
              <table className="table admin-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>User</th>
                    <SortHeader label="Merchant" field="merchant" sort={sort} onSort={(s) => update(s)} />
                    <SortHeader label="Amount" field="amount" sort={sort} onSort={(s) => update(s)} className="num" />
                    <SortHeader label="Date" field="date" sort={sort} onSort={(s) => update(s)} />
                    <th>Category</th>
                    <th>Source</th>
                    <SortHeader label="Created" field="created" sort={sort} onSort={(s) => update(s)} />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((t) => (
                    <tr key={t.id} className={`clickable ${t.deleted_at ? "row-deleted" : ""}`} tabIndex={0}
                      onClick={() => open(t)} onKeyDown={(e) => e.key === "Enter" && open(t)}>
                      <td className="mono small">{shortId(t.id)}</td>
                      <td className="small">
                        <Link to={`/admin/users/${t.user_id}`} onClick={(e) => e.stopPropagation()}>{t.user_email}</Link>
                      </td>
                      <td>{t.merchant_name}{t.deleted_at && <span className="badge badge-deleted">deleted</span>}</td>
                      <td className="num amount">{formatCurrency(t.amount)}</td>
                      <td className="small nowrap">{formatDate(t.transaction_date)}</td>
                      <td><span className="category-chip">{t.category}</span></td>
                      <td className="small">{t.source}</td>
                      <td className="small nowrap">{formatDateTime(t.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.items.length === 0 && <p className="empty">No transactions match.</p>}
            </div>
            <PagedFooter data={data} onPage={(page) => update({ page: String(page) }, true)} />
          </div>
        )}
      </section>

      {selected && !dialog && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setSelected(null)}>
          <div className="modal modal-wide" role="dialog" aria-modal="true">
            <h2>{formatCurrency(selected.amount)} · {selected.merchant_name}</h2>
            {selected.deleted_at && (
              <Alert type="warning">Deleted {formatDateTime(selected.deleted_at)}. Reason: {selected.deleted_reason}</Alert>
            )}
            <dl className="details-grid">
              <div className="detail"><dt>Transaction ID</dt><dd className="mono small">{selected.id}</dd></div>
              <div className="detail"><dt>User</dt><dd>{selected.user_email}</dd></div>
              <div className="detail"><dt>Date</dt><dd>{formatDate(selected.transaction_date)}</dd></div>
              <div className="detail"><dt>Category</dt><dd>{selected.category}</dd></div>
              <div className="detail"><dt>Payment</dt><dd>{selected.payment_method || "—"} · {selected.bank || "—"}</dd></div>
              <div className="detail"><dt>Source</dt><dd>{selected.source}{selected.extraction_method ? ` (${selected.extraction_method})` : ""}</dd></div>
              <div className="detail"><dt>UTR</dt><dd className="mono">{selected.utr_masked || "—"}</dd></div>
              <div className="detail"><dt>PhonePe ID</dt><dd className="mono">{selected.phonepe_transaction_id_masked || "—"}</dd></div>
              <div className="detail"><dt>Created</dt><dd>{formatDateTime(selected.created_at)}</dd></div>
            </dl>
            <p className="muted small">References are masked. Notes and receipt text are not visible to admins.</p>
            <div className="modal-actions">
              <button type="button" className="btn btn-secondary" onClick={() => setSelected(null)}>Close</button>
              {can(me, PERMS.txManage) && !selected.deleted_at && (
                <button type="button" className="btn btn-danger-solid" onClick={() => setDialog("delete")}>Delete…</button>
              )}
              {can(me, PERMS.txManage) && selected.deleted_at && (
                <button type="button" className="btn btn-primary" onClick={() => setDialog("restore")}>Restore…</button>
              )}
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(dialog)}
        title={dialog === "delete" ? "Delete transaction" : "Restore transaction"}
        actionLabel={dialog === "delete" ? "Delete" : "Restore"}
        danger={dialog === "delete"}
        requireReason
        consequences={dialog === "delete"
          ? "Soft delete: hidden from the user and their totals, kept in the database and in the audit log. It can be restored."
          : "The transaction becomes visible to the user again."}
        onClose={() => setDialog(null)}
        onConfirm={async ({ reason }) => {
          const updated = await adminService.transactionAction(selected.id, dialog, { reason });
          setSelected(updated);
          notify(dialog === "delete" ? "Transaction deleted" : "Transaction restored");
          reload();
        }}
      >
        <div className="confirm-target">
          {selected && <>{formatCurrency(selected.amount)} · {selected.merchant_name} · {selected.user_email}</>}
        </div>
      </ConfirmDialog>
    </div>
  );
}
