/** Small helpers shared by admin list pages. */
import Pagination from "../../components/Pagination";

export function SortHeader({ label, field, sort, onSort, className = "" }) {
  const active = sort.sort_by === field;
  const next = active && sort.sort_order === "desc" ? "asc" : "desc";
  return (
    <th className={className} aria-sort={active ? (sort.sort_order === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort-button" onClick={() => onSort({ sort_by: field, sort_order: next })}>
        {label} <span aria-hidden="true">{active ? (sort.sort_order === "asc" ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );
}

export function PagedFooter({ data, onPage, noun = "result" }) {
  if (!data) return null;
  return <Pagination page={data.page} pages={data.pages} total={data.total} onChange={onPage} noun={noun} />;
}

/** Remove empty values so they don't end up in the query string. */
export const clean = (params) => Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v != null));
