/** One-click switch between "Company" (reimbursable) and "Personal". */
export default function ReimbursableToggle({ transaction, onToggle, busy = false }) {
  const isCompany = transaction.is_reimbursable;
  const stop = (event) => event.stopPropagation(); // don't open the row when clicking the toggle
  return (
    <button
      type="button"
      className={`reimb-toggle ${isCompany ? "is-company" : ""}`}
      aria-pressed={isCompany}
      title={isCompany ? "Company reimbursable. Click to mark as personal." : "Personal. Click to mark as company reimbursable."}
      disabled={busy}
      onKeyDown={stop}
      onClick={(event) => {
        stop(event);
        onToggle(transaction);
      }}
    >
      {isCompany ? "Company" : "Personal"}
    </button>
  );
}
