import { useEffect, useState } from "react";
import { settingsService } from "../services/settingsService";

let cached = null;
const listeners = new Set();

/** Call after saving the rule in Settings so open forms use the new rule. */
export function setCachedRule(rule) {
  cached = rule;
  listeners.forEach((listener) => listener(rule));
}

/** The user's company-reimbursement rule (fetched once per page load). */
export function useReimbursementRule() {
  const [rule, setRule] = useState(cached);

  useEffect(() => {
    listeners.add(setRule);
    if (!cached) {
      settingsService
        .getReimbursementRule()
        .then(setCachedRule)
        .catch(() => {});
    }
    return () => listeners.delete(setRule);
  }, []);

  return rule;
}
