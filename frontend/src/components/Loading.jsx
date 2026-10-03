export default function Loading({ full = false, label = "Loading…" }) {
  return (
    <div className={full ? "loading loading-full" : "loading"} role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
