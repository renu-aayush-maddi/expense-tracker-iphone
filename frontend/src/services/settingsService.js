import { apiRequest } from "./api";

export const settingsService = {
  meta: () => apiRequest("/api/meta"),
  listTokens: () => apiRequest("/api/settings/tokens"),
  createToken: (name) => apiRequest("/api/settings/tokens", { method: "POST", body: { name } }),
  deleteToken: (id) => apiRequest(`/api/settings/tokens/${id}`, { method: "DELETE" }),
  listAccounts: () => apiRequest("/api/settings/accounts"),
  createAccount: (accountLast4, bankName) =>
    apiRequest("/api/settings/accounts", {
      method: "POST",
      body: { account_last4: accountLast4, bank_name: bankName },
    }),
  deleteAccount: (id) => apiRequest(`/api/settings/accounts/${id}`, { method: "DELETE" }),
};
