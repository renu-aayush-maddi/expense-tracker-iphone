import { formatCurrency } from "../../utils/format";

/**
 * Horizontal bar list sorted by amount (plain HTML/CSS – readable on any screen).
 * items: [{ label, total, count }]
 */
export default function BarList({ items, onSelect }) {
  if (!items?.length) return <p className="empty">No spending in this period.</p>;

  const max = Math.max(...items.map((i) => Number(i.total)));
  const sum = items.reduce((acc, i) => acc + Number(i.total), 0);

  return (
    <ul className="bar-list">
      {items.map((item) => {
        const value = Number(item.total);
        const share = sum ? Math.round((value / sum) * 100) : 0;
        const content = (
          <>
            <div className="bar-list-row">
              <span className="bar-list-label">{item.label}</span>
              <span className="bar-list-value">
                {formatCurrency(value)} <span className="muted small">· {share}%</span>
              </span>
            </div>
            <div className="bar-track" aria-hidden="true">
              <div className="bar-fill" style={{ width: `${max ? Math.max((value / max) * 100, 1) : 0}%` }} />
            </div>
          </>
        );
        return (
          <li key={item.label} title={`${item.count} transaction${item.count === 1 ? "" : "s"}`}>
            {onSelect ? (
              <button type="button" className="bar-list-button" onClick={() => onSelect(item.label)}>
                {content}
              </button>
            ) : (
              content
            )}
          </li>
        );
      })}
    </ul>
  );
}
