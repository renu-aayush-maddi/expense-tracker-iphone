import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatCurrency, formatCurrencyShort } from "../../utils/format";

function ChartTooltip({ active, payload, label, labelFormatter, valueFormatter = formatCurrency }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="muted small">{labelFormatter ? labelFormatter(label) : label}</div>
      <strong>{valueFormatter(payload[0].value)}</strong>
    </div>
  );
}

/**
 * Single-series column chart (one colour, so no legend — the card title names it).
 * data: [{ [xKey]: "Oct 2026", total: "12450.00" }, ...]
 */
export default function ColumnChart({
  data, xKey = "label", height = 240, tooltipLabel, tickFormatter, tableCaption, valueFormatter = formatCurrency,
}) {
  const rows = data.map((d) => ({ ...d, total: Number(d.total) }));
  const hasData = rows.some((r) => r.total > 0);

  return (
    <div>
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
                content={<ChartTooltip labelFormatter={tooltipLabel} valueFormatter={valueFormatter} />}
                isAnimationActive={false}
              />
              <Bar dataKey="total" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={24} />
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
            <tbody>
              {rows
                .filter((r) => r.total > 0)
                .map((r) => (
                  <tr key={r[xKey]}>
                    <td>{tooltipLabel ? tooltipLabel(r[xKey]) : r[xKey]}</td>
                    <td className="num">{valueFormatter(r.total)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
