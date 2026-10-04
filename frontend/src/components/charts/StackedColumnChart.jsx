import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatCurrency, formatCurrencyShort } from "../../utils/format";

/**
 * Two-part stacked columns, e.g. "Your own" + "Company reimburses" per month.
 * series: [{ key, label, color }] bottom -> top. The legend is always shown (2+ series).
 */
function StackedTooltip({ active, payload, label, series, labelFormatter, valueFormatter = formatCurrency }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const total = series.reduce((sum, s) => sum + row[s.key], 0);
  return (
    <div className="chart-tooltip">
      <div className="muted small">{labelFormatter ? labelFormatter(label) : label}</div>
      {[...series].reverse().map((s) => (
        <div key={s.key} className="tooltip-row">
          <span className="legend-swatch" style={{ background: s.color }} aria-hidden="true" />
          <span>{s.label}</span>
          <strong>{valueFormatter(row[s.key])}</strong>
        </div>
      ))}
      <div className="tooltip-row tooltip-total">
        <span />
        <span>Total</span>
        <strong>{valueFormatter(total)}</strong>
      </div>
    </div>
  );
}

export function Legend({ series }) {
  return (
    <ul className="chart-legend">
      {series.map((s) => (
        <li key={s.key}>
          <span className="legend-swatch" style={{ background: s.color }} aria-hidden="true" />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

export default function StackedColumnChart({
  data, series, xKey = "label", height = 240, tickFormatter, tooltipLabel, tableCaption, valueFormatter = formatCurrency,
}) {
  const rows = data.map((d) => {
    const row = { ...d };
    series.forEach((s) => (row[s.key] = Number(d[s.key]) || 0));
    return row;
  });
  const hasData = rows.some((r) => series.some((s) => r[s.key] > 0));
  const top = series[series.length - 1].key;

  return (
    <div>
      <Legend series={series} />
      <div className="chart" style={{ height }}>
        {hasData ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis
                dataKey={xKey}
                tickFormatter={tickFormatter}
                tickLine={false}
                axisLine={{ stroke: "var(--grid)" }}
                tick={{ fill: "var(--text-muted)", fontSize: 12 }}
                interval="preserveStartEnd"
                minTickGap={8}
              />
              <YAxis
                tickFormatter={valueFormatter === formatCurrency ? formatCurrencyShort : undefined}
                allowDecimals={valueFormatter === formatCurrency}
                tickLine={false}
                axisLine={false}
                width={56}
                tick={{ fill: "var(--text-muted)", fontSize: 12 }}
              />
              <Tooltip
                cursor={{ fill: "var(--hover)" }}
                content={<StackedTooltip series={series} labelFormatter={tooltipLabel} valueFormatter={valueFormatter} />}
                isAnimationActive={false}
              />
              {series.map((s) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  stackId="stack"
                  fill={s.color}
                  maxBarSize={24}
                  radius={s.key === top ? [4, 4, 0, 0] : 0}
                  // 2px surface-coloured gap between the stacked parts.
                  stroke="var(--surface)"
                  strokeWidth={2}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="empty">No spending in this period.</p>
        )}
      </div>
      {hasData && (
        <details className="table-view">
          <summary>Show as table</summary>
          <table className="table">
            <caption className="sr-only">{tableCaption}</caption>
            <thead>
              <tr>
                <th />
                {series.map((s) => (
                  <th key={s.key} className="num">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows
                .filter((r) => series.some((s) => r[s.key] > 0))
                .map((r) => (
                  <tr key={r[xKey]}>
                    <td>{r[xKey]}</td>
                    {series.map((s) => (
                      <td key={s.key} className="num">
                        {valueFormatter(r[s.key])}
                      </td>
                    ))}
                  </tr>
                ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
