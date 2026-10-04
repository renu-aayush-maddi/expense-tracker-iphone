import { apiDownload, apiRequest } from "../services/api";

const post = (path, body = {}) => apiRequest(path, { method: "POST", body });

// Every call is authorized again on the server – hiding a button is only cosmetic.
export const adminService = {
  dashboard: (params) => apiRequest("/api/admin/dashboard", { params }),

  users: (params) => apiRequest("/api/admin/users", { params }),
  user: (id) => apiRequest(`/api/admin/users/${id}`),
  userActivity: (id) => apiRequest(`/api/admin/users/${id}/activity`),
  userSecurity: (id) => apiRequest(`/api/admin/users/${id}/security`),
  userFinance: (id) => apiRequest(`/api/admin/users/${id}/finance`),
  updateUser: (id, body) => apiRequest(`/api/admin/users/${id}`, { method: "PATCH", body }),
  userAction: (id, action, body) => post(`/api/admin/users/${id}/${action}`, body),

  admins: () => apiRequest("/api/admin/admins"),
  addAdmin: (body) => post("/api/admin/admins", body),
  adminActivity: (id) => apiRequest(`/api/admin/admins/${id}/activity`),

  transactions: (params) => apiRequest("/api/admin/transactions", { params }),
  transaction: (id) => apiRequest(`/api/admin/transactions/${id}`),
  transactionAction: (id, action, body) => post(`/api/admin/transactions/${id}/${action}`, body),

  auditLogs: (params) => apiRequest("/api/admin/audit-logs", { params }),
  auditLog: (id) => apiRequest(`/api/admin/audit-logs/${id}`),
  auditActions: () => apiRequest("/api/admin/audit-logs/actions"),
  exportAuditLogs: (params) => apiDownload("/api/admin/audit-logs/export.csv", params, "audit-logs.csv"),

  securityEvents: (params) => apiRequest("/api/admin/security-events", { params }),
  securityEventTypes: () => apiRequest("/api/admin/security-events/types"),
  securitySummary: () => apiRequest("/api/admin/security-events/summary"),

  sessions: (params) => apiRequest("/api/admin/sessions", { params }),
  revokeSession: (id, body) => post(`/api/admin/sessions/${id}/revoke`, body),
  revokeSessionsByIp: (body) => post("/api/admin/sessions/revoke-by-ip", body),

  ipAddresses: (params) => apiRequest("/api/admin/ip-addresses", { params }),
  ipAddress: (ip) => apiRequest(`/api/admin/ip-addresses/${encodeURIComponent(ip)}`),
  ipBlocks: (params) => apiRequest("/api/admin/ip-blocks", { params }),
  blockIp: (body) => post("/api/admin/ip-blocks", body),
  unblockIp: (id, body) => post(`/api/admin/ip-blocks/${id}/unblock`, body),

  systemHealth: () => apiRequest("/api/admin/system/health"),
  report: (type, params) => apiRequest(`/api/admin/reports/${type}`, { params }),
  exportReport: (type, params) => apiDownload(`/api/admin/reports/${type}/export.csv`, params, `${type}-report.csv`),
};

export const PERMS = {
  dashboard: "dashboard:view",
  usersView: "users:view",
  usersManage: "users:manage",
  usersDelete: "users:delete",
  txView: "transactions:view",
  txManage: "transactions:manage",
  audit: "audit:view",
  securityView: "security:view",
  securityManage: "security:manage",
  system: "system:view",
  reports: "reports:view",
  export: "data:export",
  admins: "admins:manage",
};

export const can = (user, permission) => Boolean(user?.permissions?.includes(permission));
export const isAdmin = (user) => ["read_only_admin", "admin", "super_admin"].includes(user?.role);

export const ROLE_LABELS = {
  user: "User",
  read_only_admin: "Read-only admin",
  admin: "Admin",
  super_admin: "Super admin",
};
