export default function Pagination({ page, pages, total, onChange }) {
  if (!pages || pages <= 1) {
    return <div className="pagination muted small">{total} transaction{total === 1 ? "" : "s"}</div>;
  }
  return (
    <div className="pagination">
      <span className="muted small">
        {total} transactions · page {page} of {pages}
      </span>
      <div className="pagination-buttons">
        <button type="button" className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>
          ← Previous
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
        >
          Next →
        </button>
      </div>
    </div>
  );
}
