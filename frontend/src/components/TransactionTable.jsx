import { useNavigate } from "react-router-dom";
import { formatCurrency, formatDate, formatTime } from "../utils/format";
import SourceBadge from "./SourceBadge";

/** Transactions as a table on desktop; CSS turns each row into a card on mobile. */
export default function TransactionTable({ transactions, compact = false }) {
  const navigate = useNavigate();

  if (!transactions?.length) {
    return <p className="empty">No transactions found.</p>;
  }

  const open = (id) => navigate(`/transactions/${id}`);

  return (
    <div className="table-wrap">
      <table className="table table-responsive">
        <thead>
          <tr>
            <th>Date</th>
            <th>Merchant</th>
            <th>Category</th>
            {!compact && <th>Payment</th>}
            {!compact && <th>Bank</th>}
            {!compact && <th>Source</th>}
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((t) => (
            <tr
              key={t.id}
              className="clickable"
              tabIndex={0}
              onClick={() => open(t.id)}
              onKeyDown={(e) => e.key === "Enter" && open(t.id)}
            >
              <td data-label="Date">
                {formatDate(t.transaction_date)}
                {t.transaction_time && <div className="muted small">{formatTime(t.transaction_time)}</div>}
              </td>
              <td data-label="Merchant">
                <div className="merchant-cell">
                  <span className="merchant-name">{t.merchant_name}</span>
                  {t.source === "phonepe" && (
                    // Compact table: always shown. Full table: only on mobile (the Source column is hidden there).
                    <span className={compact ? "" : "mobile-only"}>
                      <SourceBadge source="phonepe" />
                    </span>
                  )}
                </div>
              </td>
              <td data-label="Category">
                <span className="category-chip">{t.category}</span>
              </td>
              {!compact && <td data-label="Payment">{t.payment_method || "—"}</td>}
              {!compact && <td data-label="Bank">{t.bank || "—"}</td>}
              {!compact && (
                <td data-label="Source">
                  <SourceBadge source={t.source} />
                </td>
              )}
              <td data-label="Amount" className="num amount">
                {formatCurrency(t.amount)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
