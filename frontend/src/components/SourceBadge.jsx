import { sourceLabel } from "../utils/format";

export default function SourceBadge({ source }) {
  return <span className={`badge badge-${source}`}>{sourceLabel(source)}</span>;
}
