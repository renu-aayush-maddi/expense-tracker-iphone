import { useEffect, useState } from "react";

/**
 * Filter bar. `filters` is a plain object of query values; `onChange(newFilters)`
 * is called whenever something changes (search is debounced).
 */
export default function TransactionFilters({ filters, options, onChange }) {
  const [search, setSearch] = useState(filters.search || "");

  // Keep the input in sync when filters are cleared from outside.
  useEffect(() => setSearch(filters.search || ""), [filters.search]);

  // Debounce typing so we don't call the API on every keystroke.
  useEffect(() => {
    if ((filters.search || "") === search) return undefined;
    const timer = setTimeout(() => onChange({ ...filters, search }), 400);
    return () => clearTimeout(timer);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (field) => (event) => onChange({ ...filters, [field]: event.target.value });

  const monthValue = filters.year && filters.month ? `${filters.year}-${String(filters.month).padStart(2, "0")}` : "";
  const setMonth = (event) => {
    const [year, month] = event.target.value ? event.target.value.split("-") : ["", ""];
    onChange({ ...filters, year, month: month ? String(Number(month)) : "" });
  };

  const sortValue = `${filters.sort_by || "date"}:${filters.sort_order || "desc"}`;
  const setSort = (event) => {
    const [sort_by, sort_order] = event.target.value.split(":");
    onChange({ ...filters, sort_by, sort_order });
  };

  const hasFilters = Object.entries(filters).some(
    ([key, value]) => value && !["sort_by", "sort_order", "page"].includes(key),
  );

  return (
    <div className="card filters">
      <div className="filters-grid">
        <label className="field span-2">
          <span>Search</span>
          <input
            type="search"
            placeholder="Merchant, notes, UTR…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Category</span>
          <select value={filters.category || ""} onChange={set("category")}>
            <option value="">All</option>
            {options.categories.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Bank</span>
          <select value={filters.bank || ""} onChange={set("bank")}>
            <option value="">All</option>
            {options.banks.map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Payment method</span>
          <select value={filters.payment_method || ""} onChange={set("payment_method")}>
            <option value="">All</option>
            {options.payment_methods.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Source</span>
          <select value={filters.source || ""} onChange={set("source")}>
            <option value="">All</option>
            <option value="manual">Manual</option>
            <option value="phonepe">PhonePe</option>
          </select>
        </label>
        <label className="field">
          <span>Month</span>
          <input type="month" value={monthValue} onChange={setMonth} />
        </label>
        <label className="field">
          <span>Exact date</span>
          <input type="date" value={filters.date || ""} onChange={set("date")} />
        </label>
        <label className="field">
          <span>From</span>
          <input type="date" value={filters.date_from || ""} onChange={set("date_from")} />
        </label>
        <label className="field">
          <span>To</span>
          <input type="date" value={filters.date_to || ""} onChange={set("date_to")} />
        </label>
        <label className="field">
          <span>Min ₹</span>
          <input type="number" min="0" step="any" value={filters.min_amount || ""} onChange={set("min_amount")} />
        </label>
        <label className="field">
          <span>Max ₹</span>
          <input type="number" min="0" step="any" value={filters.max_amount || ""} onChange={set("max_amount")} />
        </label>
        <label className="field">
          <span>Sort</span>
          <select value={sortValue} onChange={setSort}>
            <option value="date:desc">Newest first</option>
            <option value="date:asc">Oldest first</option>
            <option value="amount:desc">Amount: high → low</option>
            <option value="amount:asc">Amount: low → high</option>
            <option value="merchant:asc">Merchant A → Z</option>
            <option value="category:asc">Category</option>
          </select>
        </label>
      </div>
      {hasFilters && (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => onChange({ sort_by: filters.sort_by, sort_order: filters.sort_order })}
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
