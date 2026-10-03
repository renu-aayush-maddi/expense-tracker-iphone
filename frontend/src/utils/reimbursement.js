// Mirror of the backend rule (app/services/reimbursement.py), used to show the
// automatic choice live in forms. The server still makes the final decision.

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // index 0 = Monday

export function ruleMatches(rule, merchantName, isoDate) {
  if (!rule?.enabled || !merchantName || !isoDate) return false;
  const [year, month, day] = isoDate.split("-").map(Number);
  const weekday = (new Date(year, month - 1, day).getDay() + 6) % 7; // JS: 0 = Sunday -> make Monday 0
  if (!rule.weekdays.includes(weekday)) return false;
  const name = merchantName.toLowerCase();
  // Whole words only: "ola" matches "Ola Cabs" but not "Coca Cola".
  return rule.keywords.some((keyword) => new RegExp(`(?<![a-z0-9])${escapeRegExp(keyword)}(?![a-z0-9])`).test(name));
}
