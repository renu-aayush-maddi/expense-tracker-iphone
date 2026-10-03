import { apiRequest, ApiError } from "./api";

export const importService = {
  // The import endpoint returns a useful JSON body even for 422 "invalid",
  // so we return that body instead of throwing.
  importPhonePe: async (ocrText) => {
    try {
      return await apiRequest("/api/transactions/import/phonepe", { method: "POST", body: { ocr_text: ocrText } });
    } catch (error) {
      if (error instanceof ApiError && error.data?.status) return error.data;
      throw error;
    }
  },
  listPending: () => apiRequest("/api/imports/pending"),
  reprocessPending: () => apiRequest("/api/imports/pending/reprocess", { method: "POST" }),
  getPending: (id) => apiRequest(`/api/imports/pending/${id}`),
  confirmPending: (id, data, allowSimilar = false) =>
    apiRequest(`/api/imports/pending/${id}/confirm`, {
      method: "POST",
      body: data,
      params: allowSimilar ? { allow_similar: true } : undefined,
    }),
  discardPending: (id) => apiRequest(`/api/imports/pending/${id}`, { method: "DELETE" }),
};
