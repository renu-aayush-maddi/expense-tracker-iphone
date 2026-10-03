import { useEffect, useState } from "react";
import { settingsService } from "../services/settingsService";

const FALLBACK = {
  categories: [
    "Food", "Groceries", "Shopping", "Transport", "Bills", "Entertainment", "Health",
    "Travel", "Education", "Subscriptions", "Rent", "Utilities", "Other",
  ],
  payment_methods: ["UPI", "Debit Card", "Credit Card", "Cash", "Net Banking", "Wallet", "Other"],
  sources: ["manual", "phonepe"],
  allow_registration: true,
};

let cached = null;

/** Categories, payment methods etc. from the backend (fetched once per page load). */
export function useMeta() {
  const [meta, setMeta] = useState(cached || FALLBACK);

  useEffect(() => {
    if (cached) return;
    settingsService
      .meta()
      .then((data) => {
        cached = data;
        setMeta(data);
      })
      .catch(() => {});
  }, []);

  return meta;
}
