// Formatting helpers. Amounts arrive from the API as exact strings like "183.00".

const inrWithPaise = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2 });
const inrWhole = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

export function formatCurrency(amount) {
  if (amount === null || amount === undefined || amount === "") return "—";
  const value = Number(amount);
  if (Number.isNaN(value)) return "—";
  return Number.isInteger(value) ? inrWhole.format(value) : inrWithPaise.format(value);
}

/** Compact axis labels: ₹1.2K, ₹3.4L */
export function formatCurrencyShort(amount) {
  const value = Number(amount) || 0;
  if (value >= 100000) return `₹${+(value / 100000).toFixed(1)}L`;
  if (value >= 1000) return `₹${+(value / 1000).toFixed(1)}K`;
  return `₹${value}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "2026-10-03" -> "3 Oct 2026" (parsed as a plain date, no timezone shifts). */
export function formatDate(isoDate) {
  if (!isoDate) return "—";
  if (isoDate.length > 10) {
    // a full timestamp: show the date in the browser's timezone
    const d = new Date(isoDate);
    return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  }
  const [year, month, day] = isoDate.split("-").map(Number);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

/** "13:11:00" -> "1:11 PM" */
export function formatTime(isoTime) {
  if (!isoTime) return "—";
  const [h, m] = isoTime.split(":").map(Number);
  const suffix = h >= 12 ? "PM" : "AM";
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${suffix}`;
}

export function formatDateTime(isoDateTime) {
  if (!isoDateTime) return "—";
  return new Date(isoDateTime).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export function monthName(month, long = false) {
  return (long ? MONTHS_LONG : MONTHS)[month - 1];
}

/** Today's date as YYYY-MM-DD in the browser's timezone. */
export function todayISO() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function nowTimeHHMM() {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

export const SOURCE_LABELS = { manual: "Manual", phonepe: "PhonePe" };
export const sourceLabel = (source) => SOURCE_LABELS[source] || source;
