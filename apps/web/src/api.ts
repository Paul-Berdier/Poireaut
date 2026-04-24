/**
 * Poireaut API client — fully typed, token-aware.
 */
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const WS_URL = import.meta.env.VITE_WS_URL ?? API_URL.replace(/^http/, 'ws');
const TOKEN_KEY = 'poireaut.token';

export const env = { API_URL, WS_URL };

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}, body?: unknown): Promise<T> {
  const headers = new Headers(init.headers);
  const tok = getToken();
  if (tok) headers.set('Authorization', `Bearer ${tok}`);
  if (body !== undefined && !(body instanceof FormData)) headers.set('Content-Type', 'application/json');

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    body: body === undefined
      ? (init.body as BodyInit | null | undefined)
      : body instanceof FormData ? body : JSON.stringify(body),
  });

  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(`${res.status} — ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ─── Types ───────────────────────────────────────────

export type DataType =
  | 'email' | 'username' | 'phone' | 'name' | 'address'
  | 'url' | 'photo' | 'ip' | 'domain' | 'date_of_birth'
  | 'account' | 'location' | 'employer' | 'school' | 'family' | 'other';

export type VerificationStatus = 'unverified' | 'validated' | 'rejected';

export interface MeResponse {
  id: string;
  email: string;
  role: 'admin' | 'investigator';
}

export interface Investigation {
  id: string;
  title: string;
  description: string | null;
  status: 'active' | 'closed' | 'archived';
  created_at: string;
  updated_at: string;
}

export interface Entity {
  id: string;
  investigation_id: string;
  display_name: string;
  role: 'target' | 'related';
  notes: string | null;
}

export interface DataPoint {
  id: string;
  entity_id: string;
  type: DataType;
  value: string;
  status: VerificationStatus;
  confidence: number | null;
  source_connector_id: string | null;
  source_datapoint_id: string | null;
  source_url: string | null;
  notes: string | null;
  extracted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface GraphNode {
  id: string;
  kind: 'entity' | 'datapoint';
  label: string;
  data_type?: DataType;
  status?: VerificationStatus;
  confidence?: number | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  connector_name?: string | null;
  kind: 'pivot' | 'owns';
}

export interface Graph {
  investigation_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ─── Auth ───────────────────────────────────────────

export async function login(email: string, password: string) {
  const form = new FormData();
  form.set('username', email);
  form.set('password', password);
  const { access_token } = await request<{ access_token: string }>(
    '/auth/login', { method: 'POST' }, form,
  );
  setToken(access_token);
  return access_token;
}

export const register = (email: string, password: string) =>
  request<{ id: string; email: string }>('/auth/register', { method: 'POST' }, { email, password });

export const me = () => request<MeResponse>('/auth/me');
export const logout = () => setToken(null);

// ─── Investigations ─────────────────────────────────

export const listInvestigations = () => request<Investigation[]>('/investigations');
export const getInvestigation = (id: string) => request<Investigation>(`/investigations/${id}`);
export const createInvestigation = (title: string, description?: string) =>
  request<Investigation>('/investigations', { method: 'POST' }, { title, description });
export const deleteInvestigation = (id: string) =>
  request<void>(`/investigations/${id}`, { method: 'DELETE' });

// ─── Entities ───────────────────────────────────────

export const listEntities = (investigationId: string) =>
  request<Entity[]>(`/investigations/${investigationId}/entities`);
export const createEntity = (investigationId: string, displayName: string, role: 'target' | 'related' = 'target') =>
  request<Entity>(`/investigations/${investigationId}/entities`, { method: 'POST' }, { display_name: displayName, role });

// ─── Datapoints ─────────────────────────────────────

export const listDatapoints = (entityId: string) =>
  request<DataPoint[]>(`/entities/${entityId}/datapoints`);
export const createDatapoint = (entityId: string, type: DataType, value: string) =>
  request<DataPoint>(`/entities/${entityId}/datapoints`, { method: 'POST' }, { type, value });
export const updateDatapoint = (id: string, patch: Partial<Pick<DataPoint, 'status' | 'confidence' | 'notes'>>) =>
  request<DataPoint>(`/datapoints/${id}`, { method: 'PATCH' }, patch);
export const deleteDatapoint = (id: string) =>
  request<void>(`/datapoints/${id}`, { method: 'DELETE' });

export const pivot = (datapointId: string) =>
  request<{ task_id: string }>(`/datapoints/${datapointId}/pivot`, { method: 'POST' });

// ─── Connectors (admin) ─────────────────────────────

export type HealthStatus = 'ok' | 'degraded' | 'dead' | 'unknown';
export type ConnectorCost = 'free' | 'api_key_free_tier' | 'paid';
export type ConnectorCategory =
  | 'email' | 'username' | 'phone' | 'image' | 'domain' | 'ip'
  | 'breach' | 'people' | 'company' | 'socmint' | 'geoint' | 'archive' | 'other';

export interface ConnectorInfo {
  id: string;
  name: string;
  display_name: string;
  category: ConnectorCategory;
  description: string | null;
  homepage_url: string | null;
  input_types: DataType[];
  output_types: DataType[];
  cost: ConnectorCost;
  health: HealthStatus;
  last_health_check: string | null;
  enabled: boolean;
}

export type RunStatus = 'pending' | 'running' | 'success' | 'failed' | 'timeout';

export interface ConnectorRun {
  id: string;
  connector_id: string;
  input_datapoint_id: string | null;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  result_count: number;
  error_message: string | null;
  created_at: string;
}

export const listConnectors = () => request<ConnectorInfo[]>('/connectors');
export const listConnectorRuns = (id: string, limit = 20) =>
  request<ConnectorRun[]>(`/connectors/${id}/runs?limit=${limit}`);
export const triggerHealthcheck = () =>
  request<{ task_id: string; message: string }>('/connectors/healthcheck', { method: 'POST' });

// ─── Graph ──────────────────────────────────────────

export const getGraph = (investigationId: string) =>
  request<Graph>(`/investigations/${investigationId}/graph`);

// ─── WebSocket for live updates ─────────────────────

export interface WsEvent {
  type: string;
  [k: string]: unknown;
}

export function openInvestigationSocket(
  investigationId: string,
  onMessage: (ev: WsEvent) => void,
  onStatusChange?: (s: 'connecting' | 'open' | 'closed') => void,
): () => void {
  const token = getToken();
  if (!token) throw new Error('Pas de session active');

  const url = `${WS_URL}/ws/investigations/${investigationId}?token=${encodeURIComponent(token)}`;
  let ws: WebSocket | null = null;
  let closed = false;
  let retry = 0;

  const connect = () => {
    onStatusChange?.('connecting');
    ws = new WebSocket(url);
    ws.onopen = () => { retry = 0; onStatusChange?.('open'); };
    ws.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data) as WsEvent); }
      catch { /* ignore non-JSON */ }
    };
    ws.onclose = () => {
      onStatusChange?.('closed');
      if (closed) return;
      // Exponential back-off up to 10s
      const delay = Math.min(10_000, 500 * 2 ** retry);
      retry += 1;
      setTimeout(connect, delay);
    };
    ws.onerror = () => { /* noop — onclose will handle */ };
  };

  connect();
  return () => { closed = true; ws?.close(); };
}
