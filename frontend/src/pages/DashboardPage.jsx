import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import BarList from "../components/charts/BarList";
import ColumnChart from "../components/charts/ColumnChart";
import StackedColumnChart from "../components/charts/StackedColumnChart";
import Loading from "../components/Loading";
import StatCard from "../components/StatCard";
import TransactionTable from "../components/TransactionTable";
import { useApi } from "../hooks/useApi";
import { statsService, transactionService } from "../services/transactionService";
import { formatCurrency, formatDate, monthName } from "../utils/format";

const REIMBURSEMENT_SERIES = [
  { key: "personal", label: "Your own", color: "var(--series-1)" },
  { key: "reimbursable", label: "Company reimburses", color: "var(--series-2)" },
];

function currentMonthValue() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [monthValue, setMonthValue] = useState(currentMonthValue());
  const [year, month] = monthValue.split("-").map(Number);
  const { data, loading, error, reload } = useApi(() => statsService.dashboard(year, month), [year, month]);

  const [actionError, setActionError] = useState("");
  const monthLabel = `${monthName(month, true)} ${year}`;

  const toggleReimbursable = async (transaction) => {
    setActionError("");
    try {
      await transactionService.setReimbursable(transaction.id, !transaction.is_reimbursable);
      await reload(); // totals change too
    } catch (err) {
      setActionError(err.message);
    }
  };

  const downloadClaim = async () => {
    setActionError("");
    try {
      const filename = `reimbursements-${year}-${String(month).padStart(2, "0")}.csv`;
      await transactionService.exportCsv({ reimbursable: true, year, month }, filename);
    } catch (err) {
      setActionError(err.message);
    }
  };
  const isCurrentMonth = monthValue === currentMonthValue();
  const filterLink = (field) => (label) =>
    navigate(`/transactions?year=${year}&month=${month}&${field}=${encodeURIComponent(label)}`);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Spending for {monthLabel}</p>
        </div>
        <div className="page-actions">
          <input
            type="month"
            className="month-picker"
            aria-label="Choose month"
            value={monthValue}
            max={currentMonthValue()}
            onChange={(e) => e.target.value && setMonthValue(e.target.value)}
          />
          <Link to="/add-expense" className="btn btn-primary">
            + Add expense
          </Link>
        </div>
      </div>

      {error && (
        <Alert type="error">
          {error.message}{" "}
          <button type="button" className="link-button" onClick={reload}>
            Retry
          </button>
        </Alert>
      )}

      {actionError && (
        <Alert type="error" onClose={() => setActionError("")}>
          {actionError}
        </Alert>
      )}

      {loading && !data && <Loading />}

      {data && (
        <>
          {data.pending_reviews > 0 && (
            <Alert type="warning" title={
                data.pending_reviews === 1
                  ? "1 PhonePe import needs your review"
                  : `${data.pending_reviews} PhonePe imports need your review`
              }>
              <Link to="/import">Review them now</Link> — they were not saved because some details were unclear.
            </Alert>
          )}

          <div className="stats-grid">
            <StatCard
              label={`Spent in ${monthName(month)}`}
              value={formatCurrency(data.month_total)}
              hint={Number(data.month_reimbursable_total) > 0 ? `${formatCurrency(data.month_reimbursable_total)} reimbursable` : null}
            />
            <StatCard label="Today" value={formatCurrency(data.today_total)} hint={isCurrentMonth ? null : "Always today"} />
            <StatCard label="Transactions" value={data.month_count} hint={monthLabel} />
            <StatCard label="Average" value={formatCurrency(data.month_average)} hint="per transaction" />
            <StatCard
              label="Largest"
              value={data.largest_transaction ? formatCurrency(data.largest_transaction.amount) : "—"}
              hint={
                data.largest_transaction
                  ? `${data.largest_transaction.merchant_name} · ${formatDate(data.largest_transaction.transaction_date)}`
                  : null
              }
            />
          </div>

          <section className="card">
            <div className="card-header reimb-header">
              <div>
                <h2>Company reimbursements</h2>
                <p className="muted small">{monthLabel}: rides on weekdays plus anything you marked as company</p>
              </div>
              <div className="page-actions">
                <Link
                  to={`/transactions?reimbursable=true&year=${year}&month=${month}`}
                  className="btn btn-secondary btn-sm"
                >
                  View list
                </Link>
                <button type="button" className="btn btn-secondary btn-sm" onClick={downloadClaim}>
                  Download CSV
                </button>
              </div>
            </div>

            <div className="reimb-summary">
              <div className="reimb-stat">
                <span className="stat-label">
                  <span className="legend-swatch" style={{ background: "var(--series-2)" }} aria-hidden="true" />
                  Company will reimburse
                </span>
                <span className="stat-value">{formatCurrency(data.month_reimbursable_total)}</span>
                <span className="stat-hint">
                  {data.month_reimbursable_count} transaction{data.month_reimbursable_count === 1 ? "" : "s"}
                </span>
              </div>
              <div className="reimb-stat">
                <span className="stat-label">
                  <span className="legend-swatch" style={{ background: "var(--series-1)" }} aria-hidden="true" />
                  Your own spending
                </span>
                <span className="stat-value">{formatCurrency(data.month_personal_total)}</span>
                <span className="stat-hint">
                  {Number(data.month_total) > 0
                    ? `${Math.round((Number(data.month_personal_total) / Number(data.month_total)) * 100)}% of ${formatCurrency(data.month_total)} spent`
                    : "Nothing spent yet"}
                </span>
              </div>
            </div>

            {Number(data.month_total) > 0 && (
              <div
                className="share-bar"
                role="img"
                aria-label={`${formatCurrency(data.month_personal_total)} your own, ${formatCurrency(data.month_reimbursable_total)} reimbursed by the company`}
              >
                <div className="share-own" style={{ flexGrow: Number(data.month_personal_total) }} />
                <div className="share-company" style={{ flexGrow: Number(data.month_reimbursable_total) }} />
              </div>
            )}

            <h3 className="chart-title">Last 12 months</h3>
            <StackedColumnChart
              data={data.monthly_trend}
              series={REIMBURSEMENT_SERIES}
              tickFormatter={(label) => label.split(" ")[0]}
              tableCaption="Monthly spending split into your own and company-reimbursed"
            />
          </section>

          <div className="grid-2">
            <section className="card">
              <h2>Monthly spending</h2>
              <p className="muted small">Last 12 months</p>
              <ColumnChart
                data={data.monthly_trend}
                tickFormatter={(label) => label.split(" ")[0]}
                tableCaption="Monthly spending"
              />
            </section>
            <section className="card">
              <h2>Daily spending</h2>
              <p className="muted small">{monthLabel}</p>
              <ColumnChart
                data={data.daily}
                xKey="day"
                tooltipLabel={(day) => `${day} ${monthName(month)} ${year}`}
                tableCaption="Daily spending"
              />
            </section>
          </div>

          <div className="grid-3">
            <section className="card">
              <h2>By category</h2>
              <BarList items={data.by_category} onSelect={filterLink("category")} />
            </section>
            <section className="card">
              <h2>By bank</h2>
              <BarList items={data.by_bank} onSelect={(label) => label !== "Unknown" && filterLink("bank")(label)} />
            </section>
            <section className="card">
              <h2>By payment method</h2>
              <BarList
                items={data.by_payment_method}
                onSelect={(label) => label !== "Unknown" && filterLink("payment_method")(label)}
              />
            </section>
          </div>

          <div className="grid-2 grid-2-wide">
            <section className="card">
              <div className="card-header">
                <h2>Recent transactions</h2>
                <Link to="/transactions" className="small">
                  View all →
                </Link>
              </div>
              <TransactionTable
                transactions={data.recent_transactions}
                compact
                onToggleReimbursable={toggleReimbursable}
              />
            </section>
            <section className="card">
              <h2>Yearly spending</h2>
              {data.yearly.length ? (
                <table className="table">
                  <tbody>
                    {[...data.yearly].reverse().map((y) => (
                      <tr key={y.year}>
                        <td>{y.year}</td>
                        <td className="num amount">{formatCurrency(y.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="empty">No transactions yet.</p>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
