/**
 * Tiny API client for Poireaut.
 *
 * Keeps auth in localStorage, attaches the bearer token to every request,
 * and exposes typed helpers for the endpoints we use.
 */
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const TOKEN_KEY = 'poireaut.token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  body?: unknown,
): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (body !== undefined && !(body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    body:
      body === undefined
        ? (init.body as BodyInit | null | undefined)
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status} — ${detail}`);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ─── Auth ────────────────────────────────────────────────

export async function login(email: string, password: string) {
  const form = new FormData();
  form.set('username', email);
  form.set('password', password);
  const { access_token } = await request<{ access_token: string }>(
    '/auth/login',
    { method: 'POST' },
    form,
  );
  setToken(access_token);
  return access_token;
}

export async function register(email: string, password: string) {
  return request<{ id: string; email: string }>(
    '/auth/register',
    { method: 'POST' },
    { email, password },
  );
}

export interface MeResponse {
  id: string;
  email: string;
  role: 'admin' | 'investigator';
}

export async function me() {
  return request<MeResponse>('/auth/me');
}

export function logout() {
  setToken(null);
}

// ─── Investigations ──────────────────────────────────────

export interface Investigation {
  id: string;
  title: string;
  description: string | null;
  status: 'active' | 'closed' | 'archived';
  created_at: string;
  updated_at: string;
}

export async function listInvestigations() {
  return request<Investigation[]>('/investigations');
}

export async function createInvestigation(title: string, description?: string) {
  return request<Investigation>(
    '/investigations',
    { method: 'POST' },
    { title, description },
  );
}
