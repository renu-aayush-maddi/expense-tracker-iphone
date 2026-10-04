/** Readable, escaped JSON (React escapes text, so metadata can't inject HTML). */
export default function JsonView({ value }) {
  if (!value || (typeof value === "object" && Object.keys(value).length === 0)) {
    return <span className="muted">No details</span>;
  }
  return <pre className="json-view">{JSON.stringify(value, null, 2)}</pre>;
}
