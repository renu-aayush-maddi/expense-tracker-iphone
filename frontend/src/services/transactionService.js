import { apiRequest } from "./api";

export const transactionService = {
  list: (params) => apiRequest("/api/transactions", { params }),
  get: (id) => apiRequest(`/api/transactions/${id}`),
  create: (data) => apiRequest("/api/transactions", { method: "POST", body: data }),
  update: (id, data) => apiRequest(`/api/transactions/${id}`, { method: "PUT", body: data }),
  remove: (id) => apiRequest(`/api/transactions/${id}`, { method: "DELETE" }),
  filterOptions: () => apiRequest("/api/transactions/filter-options"),
};

export const statsService = {
  dashboard: (year, month) => apiRequest("/api/stats/dashboard", { params: { year, month } }),
};
