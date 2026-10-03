// Small fetch wrapper: adds the JWT, parses JSON and turns errors into friendly messages.

export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");

const TOKEN_KEY = "expense_tracker_token";

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

let unauthorizedHandler = null;
export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

const STATUS_MESSAGES = {
  400: "That request wasn't valid.",
  401: "Your session has expired. Please log in again.",
  403: "You don't have permission to do that.",
  404: "We couldn't find that.",
  409: "This already exists.",
  413: "That's too large to upload.",
  422: "Please check the highlighted values.",
  429: "Too many requests. Please wait a minute and try again.",
  500: "Something went wrong on our side. Please try again.",
};

function friendlyMessage(status, data) {
  const detail = data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object" && detail.message) return detail.message;
  if (data?.message) return data.message;
  return STATUS_MESSAGES[status] || (status >= 500 ? STATUS_MESSAGES[500] : "Something went wrong.");
}

function buildUrl(path, params) {
  const url = new URL(API_URL + path);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  });
  return url.toString();
}

/** Download a file (e.g. CSV) from an authenticated endpoint. */
export async function apiDownload(path, params, filename) {
  const token = tokenStore.get();
  let response;
  try {
    response = await fetch(buildUrl(path, params), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  } catch {
    throw new ApiError("Can't reach the server. Please try again.", 0, null);
  }
  if (!response.ok) {
    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    throw new ApiError(friendlyMessage(response.status, data), response.status, data);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function apiRequest(path, { method = "GET", body, params } = {}) {
  const headers = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(buildUrl(path, params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(
      "Can't reach the server. If it was asleep (Render free plan), wait up to a minute and try again.",
      0,
      null,
    );
  }

  if (response.status === 204) return null;

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    if (response.status === 401 && token && unauthorizedHandler) unauthorizedHandler();
    throw new ApiError(friendlyMessage(response.status, data), response.status, data);
  }
  return data;
}
