const RANGES = [
  ["today", "Today"],
  ["7d", "7 days"],
  ["30d", "30 days"],
  ["90d", "90 days"],
  ["custom", "Custom"],
];

/** value: { range, start, end } */
export default function RangePicker({ value, onChange }) {
  return (
    <div className="range-picker">
      <div className="segmented" role="group" aria-label="Date range">
        {RANGES.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={value.range === key ? "is-active" : ""}
            aria-pressed={value.range === key}
            onClick={() => onChange({ ...value, range: key })}
          >
            {label}
          </button>
        ))}
      </div>
      {value.range === "custom" && (
        <div className="range-custom">
          <input type="date" aria-label="Start date" value={value.start || ""} onChange={(e) => onChange({ ...value, start: e.target.value })} />
          <span className="muted">to</span>
          <input type="date" aria-label="End date" value={value.end || ""} onChange={(e) => onChange({ ...value, end: e.target.value })} />
        </div>
      )}
    </div>
  );
}

/** Query params for the API; null while a custom range is incomplete. */
export function rangeParams(value) {
  if (value.range !== "custom") return { range: value.range };
  if (!value.start || !value.end) return null;
  return { range: "custom", start: value.start, end: value.end };
}
