/**
 * API client — fetch() wrappers for all /api/* endpoints.
 * All functions return typed objects/arrays or throw on error.
 */

import type {
  Trip,
  Flight,
  Airport,
  SyncStatus,
  Settings,
  AircraftInfo,
  EmailData,
  TripsListResponse,
  AirportCountResponse,
  User,
  UserListItem,
  LoginResponse,
} from './types';

const BASE = ''; // Same origin; Vite proxy handles /api in dev

interface RequestOptions {
  method: string;
  headers: Record<string, string>;
  body?: string;
  credentials: RequestCredentials;
}

async function _request<T>(method: string, path: string, body: unknown = null): Promise<T> {
  const opts: RequestOptions = {
    method,
    headers: {},
    credentials: 'include',
  };
  if (body !== null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(BASE + path, opts);

  if (res.status === 204) return null as T;

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const d = data as { detail?: string; error?: string; message?: string; setup_required?: boolean };
    // Special marker so App.svelte can detect first-run state
    if (res.status === 503 && d.setup_required) {
      throw new Error('setup_required');
    }
    const message = d.detail || d.error || d.message || `HTTP ${res.status}`;
    throw new Error(message);
  }

  return data as T;
}

const get = <T>(path: string) => _request<T>('GET', path);
const post = <T>(path: string, body?: unknown) => _request<T>('POST', path, body ?? null);
const patch = <T>(path: string, body?: unknown) => _request<T>('PATCH', path, body ?? null);
const del = <T>(path: string) => _request<T>('DELETE', path);

// ---- Auth ----

export const authApi = {
  setup: (data: { username: string; password: string; smtp_recipient_address?: string }) =>
    post<User>('/api/auth/setup', data),
  login: (data: { username: string; password: string }) =>
    post<LoginResponse>('/api/auth/login', data),
  logout: () => post<{ ok: boolean }>('/api/auth/logout'),
  me: () => get<User>('/api/auth/me'),
  changePassword: (data: { current_password: string; new_password: string; totp_code?: string }) =>
    post<{ ok: boolean }>('/api/auth/change-password', data),
  setup2fa: () => get<{ secret: string; uri: string }>('/api/auth/2fa/setup'),
  enable2fa: (code: string) => post<{ ok: boolean }>('/api/auth/2fa/enable', { code }),
  disable2fa: (data: { code?: string; password?: string }) =>
    post<{ ok: boolean }>('/api/auth/2fa/disable', data),
  verify2fa: (code: string) => post<User>('/api/auth/2fa/verify', { code }),
};

// ---- Users ----

export const usersApi = {
  list: () => get<UserListItem[]>('/api/users'),
  create: (data: { username: string; password: string; is_admin?: boolean; smtp_recipient_address?: string }) =>
    post<User>('/api/users', data),
  update: (id: number, data: { is_admin?: boolean; smtp_recipient_address?: string; new_password?: string }) =>
    _request<{ ok: boolean }>('PATCH', `/api/users/${id}`, data),
  delete: (id: number) => del<{ ok: boolean }>(`/api/users/${id}`),
};

// ---- Trips ----

export const tripsApi = {
  list: () => get<TripsListResponse>('/api/trips'),
  get: (id: number | string) => get<Trip>(`/api/trips/${id}`),
  create: (data: Partial<Trip>) => post<Trip>('/api/trips', data),
  update: (id: number | string, data: Partial<Trip>) => patch<Trip>(`/api/trips/${id}`, data),
  delete: (id: number | string) => del<null>(`/api/trips/${id}`),
  addFlight: (tripId: number | string, flightId: number | string) =>
    post<null>(`/api/trips/${tripId}/flights/${flightId}`),
  removeFlight: (tripId: number | string, flightId: number | string) =>
    del<null>(`/api/trips/${tripId}/flights/${flightId}`),
};

// ---- Flights ----

export interface FlightListParams {
  tripId?: number | string;
  status?: string;
  limit?: number;
  offset?: number;
}

export const flightsApi = {
  list: (params: FlightListParams = {}) => {
    const qs = new URLSearchParams();
    if (params.tripId) qs.set('trip_id', String(params.tripId));
    if (params.status) qs.set('status', params.status);
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.offset) qs.set('offset', String(params.offset));
    const q = qs.toString() ? `?${qs}` : '';
    return get<Flight[]>(`/api/flights${q}`);
  },
  get: (id: number | string) => get<Flight>(`/api/flights/${id}`),
  aircraft: (id: number | string) => get<AircraftInfo>(`/api/flights/${id}/aircraft`),
  email: (id: number | string) => get<EmailData>(`/api/flights/${id}/email`),
  create: (data: Partial<Flight>) => post<Flight>('/api/flights', data),
  update: (id: number | string, data: Partial<Flight>) =>
    patch<Flight>(`/api/flights/${id}`, data),
  delete: (id: number | string) => del<null>(`/api/flights/${id}`),
};

// ---- Sync ----

export const syncApi = {
  status: () => get<SyncStatus>('/api/sync/status'),
  now: () => post<null>('/api/sync/now'),
  regroup: () => post<null>('/api/sync/regroup'),
  resetAndSync: () => post<null>('/api/sync/reset-and-sync'),
};

// ---- Airports ----

export const airportsApi = {
  get: (iata: string) => get<Airport>(`/api/airports/${iata}`),
};

// ---- Settings ----

export interface SettingsUpdatePayload {
  gmail_address?: string;
  gmail_app_password?: string;
  sync_interval_minutes?: number;
}

export const settingsApi = {
  get: () => get<Settings>('/api/settings'),
  update: (data: SettingsUpdatePayload) => post<Settings>('/api/settings', data),
  airportCount: () => get<AirportCountResponse>('/api/settings/airports/count'),
  reloadAirports: () => post<AirportCountResponse>('/api/settings/airports/reload'),
};
