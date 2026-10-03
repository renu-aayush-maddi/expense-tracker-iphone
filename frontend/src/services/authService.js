import { apiRequest } from "./api";

export const authService = {
  register: (email, password, fullName) =>
    apiRequest("/api/auth/register", {
      method: "POST",
      body: { email, password, full_name: fullName || null },
    }),
  login: (email, password) => apiRequest("/api/auth/login", { method: "POST", body: { email, password } }),
  me: () => apiRequest("/api/auth/me"),
};
