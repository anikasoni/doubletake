// Typed fetch wrappers for the doubletake FastAPI backend.
//
// In development, requests go through the Vite proxy (see vite.config.ts):
// "/api/payments" -> "http://localhost:8000/payments". Override the base by
// setting VITE_API_BASE to talk to the backend directly:
//   - "http://localhost:8000" for a local backend
//   - "https://doubletake-backend.up.railway.app" for a deployed backend
// When VITE_API_BASE is a full URL, fetch() requests go straight there and the
// dev proxy is bypassed entirely. The server must allow the frontend origin via
// CORS (see ALLOWED_ORIGIN in app/main.py). A trailing slash is tolerated.

import type { Payment, PaymentDetail, ProcessResult } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    ...init,
  });

  let payload: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : res.statusText;
    throw new ApiError(res.status, detail, payload);
  }

  return payload as T;
}

/** GET /payments — list every payment. */
export function getPayments(): Promise<Payment[]> {
  return request<Payment[]>("/payments");
}

/** GET /payments/{id} — payment plus full investigation detail once processed. */
export function getPayment(id: string): Promise<PaymentDetail> {
  return request<PaymentDetail>(`/payments/${encodeURIComponent(id)}`);
}

/** POST /payments/{id}/process — run the allocation workflow for one payment. */
export function processPayment(id: string): Promise<ProcessResult> {
  return request<ProcessResult>(
    `/payments/${encodeURIComponent(id)}/process`,
    { method: "POST" },
  );
}
