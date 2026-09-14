/**
 * API client — fetch() wrappers for all /api/* endpoints.
 * All functions return typed objects/arrays or throw on error.
 */

import type {
  Trip,
  PackingItem,
  TripExpense,
  Participant,
  Guest,
  Balances,
  Flight,
  PaginatedFlights,
  Airport,
  SyncStatus,
  Settings,
  AircraftInfo,
  EmailData,
  TripsListResponse,
  AirportCountResponse,
  ImmichAlbumResponse,
  NotifPreferences,
  BoardingPass,
  TripBoardingPass,
  TripDocument,
  User,
  UserListItem,
  LoginResponse,
  TripShare,
  TripInvitation,
  TrustedUser,
  TripDayNote,
  InAppNotification,
  VersionInfo,
  TripSegment,
  SegmentType,
  TripStay,
  StayKind,
  StationResult,
  IntegrationStatus,
  PlaceResult,
} from './types';

const BASE = ''; // Same origin; Vite proxy handles /api in dev

interface RequestOptions {
  method: string;
  headers: Record<string, string>;
  body?: string;
  credentials: RequestCredentials;
}

/** Thrown for API errors that carry a machine-readable code + params, so the
 * caller can render a translated message instead of the raw (English-only) detail. */
export class ApiError extends Error {
  code?: string;
  params?: Record<string, string | number>;

  constructor(message: string, code?: string, params?: Record<string, string | number>) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.params = params;
  }
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
    const d = data as { detail?: unknown; error?: string; message?: string; setup_required?: boolean };
    // Special marker so App.svelte can detect first-run state
    if (res.status === 503 && d.setup_required) {
      throw new Error('setup_required');
    }
    if (d.detail && typeof d.detail === 'object') {
      const nested = d.detail as { message?: string; error?: string; params?: Record<string, string | number> };
      throw new ApiError(nested.message || `HTTP ${res.status}`, nested.error, nested.params);
    }
    const detail = typeof d.detail === 'string' ? d.detail : undefined;
    const message = detail || d.error || d.message || `HTTP ${res.status}`;
    throw new Error(message);
  }

  return data as T;
}

const get = <T>(path: string) => _request<T>('GET', path);
const post = <T>(path: string, body?: unknown) => _request<T>('POST', path, body ?? null);
const put = <T>(path: string, body?: unknown) => _request<T>('PUT', path, body ?? null);
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
  updateMe: (data: { locale?: string; accent?: string }) =>
    patch<{ ok: boolean }>('/api/auth/me', data),
};

// ---- Users ----

export const usersApi = {
  list: () => get<UserListItem[]>('/api/users'),
  create: (data: { username: string; password: string; is_admin?: boolean; smtp_recipient_address?: string }) =>
    post<User>('/api/users', data),
  update: (id: string | number, data: { is_admin?: boolean; smtp_recipient_address?: string; new_password?: string }) =>
    _request<{ ok: boolean }>('PATCH', `/api/users/${id}`, data),
  delete: (id: string | number) => del<{ ok: boolean }>(`/api/users/${id}`),
};

// ---- Trips ----

/** A trip end as the picker hands it over. The backend flattens this into the
 * `origin_*` / `destination_*` columns; an empty name clears the whole set. */
export interface TripPlaceInput {
  name: string;
  lat: number | null;
  lon: number | null;
  country_code: string | null;
}

export const tripsApi = {
  list: () => get<TripsListResponse>('/api/trips'),
  get: (id: number | string) => get<Trip>(`/api/trips/${id}`),
  create: (data: {
    name: string;
    start_date?: string;
    end_date?: string;
    origin_airport?: string;
    destination_airport?: string;
    booking_refs?: string[];
    origin?: TripPlaceInput;
    destinations?: TripPlaceInput[];
  }) => post<{ id: string }>('/api/trips', data),
  update: (id: number | string, data: Partial<Trip> & { origin?: TripPlaceInput; destinations?: TripPlaceInput[] }) =>
    patch<Trip>(`/api/trips/${id}`, data),
  delete: (id: number | string) => del<null>(`/api/trips/${id}`),
  addFlight: (tripId: number | string, flightId: number | string) =>
    post<null>(`/api/trips/${tripId}/flights/${flightId}`),
  removeFlight: (tripId: number | string, flightId: number | string) =>
    del<null>(`/api/trips/${tripId}/flights/${flightId}`),
  imageUrl: (id: string) => `/api/trips/${id}/image`,
  refreshImage: (id: string) => post<{ ok: boolean }>(`/api/trips/${id}/image/refresh`),
  createImmichAlbum: (id: string) => post<ImmichAlbumResponse>(`/api/trips/${id}/immich-album`),
  checkImmichAlbum: (id: string) => get<{ album_id: string | null; exists: boolean }>(`/api/trips/${id}/immich-album/status`),
  setRating: (id: string, rating: number | null) => put<{ rating: number | null }>(`/api/trips/${id}/rating`, { rating }),
  setNote: (id: string, note: string | null) => put<{ note: string | null }>(`/api/trips/${id}/note`, { note }),
  merge: (id: string, targetTripId: string) => post<{ target_trip_id: string }>(`/api/trips/${id}/merge`, { target_trip_id: targetTripId }),
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
    return get<PaginatedFlights>(`/api/flights${q}`);
  },
  get: (id: number | string) => get<Flight>(`/api/flights/${id}`),
  aircraft: (id: number | string) => get<AircraftInfo>(`/api/flights/${id}/aircraft`),
  email: (id: number | string) => get<EmailData>(`/api/flights/${id}/email`),
  create: (data: Partial<Flight>) => post<Flight>('/api/flights', data),
  update: (id: number | string, data: Partial<Flight>) =>
    patch<Flight>(`/api/flights/${id}`, data),
  delete: (id: number | string) => del<null>(`/api/flights/${id}`),
  ungroup: (id: number | string) => post<{ trip_id: string }>(`/api/flights/${id}/ungroup`),
};

// ---- Trip Sharing ----

export const sharesApi = {
  shareTrip: (tripId: string, username: string) =>
    post<{ ok: boolean; status: string }>(`/api/trips/${tripId}/share`, { username }),
  listTripShares: (tripId: string) => get<TripShare[]>(`/api/trips/${tripId}/shares`),
  revokeTripShare: (tripId: string, userId: number) =>
    del<null>(`/api/trips/${tripId}/shares/${userId}`),
  leaveTrip: (tripId: string) => del<null>(`/api/trips/${tripId}/leave`),
  listInvitations: () => get<TripInvitation[]>('/api/trips/invitations'),
  acceptInvitation: (shareId: number) =>
    post<{ ok: boolean }>(`/api/trips/invitations/${shareId}/accept`),
  rejectInvitation: (shareId: number) =>
    post<{ ok: boolean }>(`/api/trips/invitations/${shareId}/reject`),
  listTrustedUsers: () => get<TrustedUser[]>('/api/settings/trusted-users'),
  addTrustedUser: (username: string) =>
    post<{ ok: boolean }>('/api/settings/trusted-users', { username }),
  removeTrustedUser: (userId: number) =>
    del<null>(`/api/settings/trusted-users/${userId}`),
};

// ---- Boarding Passes ----

export const boardingPassesApi = {
  list: (flightId: string | number) =>
    get<BoardingPass[]>(`/api/flights/${flightId}/boarding-passes`),
  upload: async (flightId: string | number, file: File): Promise<{ id: string }> => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`/api/flights/${flightId}/boarding-passes`, {
      method: 'POST',
      body: form,
      credentials: 'include',
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({})) as { detail?: string };
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },
  imageUrl: (bpId: string) => `/api/boarding-passes/${bpId}/image`,
  delete: (bpId: string) => del<null>(`/api/boarding-passes/${bpId}`),
  listForTrip: (tripId: string) => get<TripBoardingPass[]>(`/api/trips/${tripId}/boarding-passes`),
};

// ---- Trip Documents ----

export const tripDocumentsApi = {
  list: (tripId: string) => get<TripDocument[]>(`/api/trips/${tripId}/documents`),
  upload: async (tripId: string, file: File): Promise<{ id: string; page_count: number }> => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`/api/trips/${tripId}/documents`, {
      method: 'POST',
      body: form,
      credentials: 'include',
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({})) as { detail?: string };
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },
  viewUrl: (docId: string, page = 0) => `/api/documents/${docId}/view?page=${page}`,
  delete: (docId: string) => del<null>(`/api/documents/${docId}`),
};

// ---- Sync ----

export const syncApi = {
  status: () => get<SyncStatus>('/api/sync/status'),
  now: () => post<null>('/api/sync/now'),
  regroup: () => post<null>('/api/sync/regroup'),
  fullSync: () => post<null>('/api/sync/full-sync'),
  uploadEml: async (files: File[]): Promise<{ emails_processed: number; flights_created: number; flights_updated: number }> => {
    const form = new FormData();
    for (const f of files) form.append('files', f);
    const res = await fetch('/api/sync/upload-eml', { method: 'POST', body: form, credentials: 'include' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail ?? res.statusText);
    }
    return res.json();
  },
};

// ---- Airports ----

// ---- Stats ----

export const statsApi = {
  get: (year?: number) =>
    get<{
      total_km: number;
      total_co2_kg: number;
      total_flights: number;
      total_hours: number;
      unique_airports: number;
      unique_countries: number;
      /** Exact counts from ground legs and stays. There is deliberately no
       * ground distance — see the stats service for why. */
      ground_legs: number;
      nights_away: number;
      earth_laps: number;
      longest_flight_km: number;
      longest_flight_route: string;
      top_routes: { key: string; count: number }[];
      top_airports: { key: string; count: number }[];
      top_airlines: { key: string; count: number; label: string | null }[];
      years: string[];
      visited_countries: string[];
      flights_by_period: { label: string; count: number }[];
      flight_breakdown: { route: string; flight: string; km: number; co2_kg: number; trip_name: string }[];
    }>(`/api/stats${year ? `?year=${year}` : ''}`),
};

export const airportsApi = {
  get: (iata: string) => get<Airport>(`/api/airports/${iata}`),
  search: (q: string) => get<Airport[]>(`/api/airports/search?q=${encodeURIComponent(q)}`),
};

// ---- Settings ----

export interface SettingsUpdatePayload {
  gmail_address?: string;
  gmail_app_password?: string;
  sync_interval_minutes?: number;
  immich_url?: string;
  immich_api_key?: string;
  default_currency?: string;
}

// ---- Notifications ----

export const notificationsApi = {
  vapidPublicKey: () => get<{ public_key: string }>('/api/notifications/vapid-public-key'),
  vapidStatus: () => get<{ configured: boolean; source: string; public_key: string | null }>('/api/notifications/vapid/status'),
  generateVapidKeys: () => post<{ ok: boolean; public_key: string; source: string }>('/api/notifications/vapid/generate'),
  subscribe: (subscription: PushSubscriptionJSON) =>
    post<{ ok: boolean }>('/api/notifications/subscribe', { subscription }),
  unsubscribe: (endpoint: string) =>
    _request<{ ok: boolean }>('DELETE', '/api/notifications/subscribe', { endpoint }),
  getPreferences: () => get<NotifPreferences>('/api/notifications/preferences'),
  updatePreferences: (prefs: Partial<NotifPreferences>) =>
    post<NotifPreferences & { ok: boolean }>('/api/notifications/preferences', prefs),
  testPush: () => post<{ ok: boolean; sent: number }>('/api/notifications/test'),
  clearBadge: () => post<{ ok: boolean }>('/api/notifications/badge/clear'),
  inbox: () => get<InAppNotification[]>('/api/notifications/inbox'),
  inboxCount: () => get<{ unread: number }>('/api/notifications/inbox/count'),
  markAllRead: () => post<{ ok: boolean; marked: number }>('/api/notifications/inbox/read-all'),
  markRead: (id: number) => post<{ ok: boolean }>(`/api/notifications/inbox/${id}/read`),
  deleteNotification: (id: number) => del<null>(`/api/notifications/inbox/${id}`),
};

export const dayNotesApi = {
  list: (tripId: string) => get<TripDayNote[]>(`/api/trips/${tripId}/day-notes`),
  upsert: (tripId: string, date: string, content: string) =>
    _request<{ ok: boolean }>('PATCH', `/api/trips/${tripId}/day-notes/${date}`, { content }),
};

export interface ExpenseWriteData {
  description: string;
  amount: number;
  currency: string;
  paid_by?: { type: 'user' | 'guest'; id: number };
  participants?: { type: 'user' | 'guest'; id: number }[];
}

export const expensesApi = {
  list: (tripId: string) => get<TripExpense[]>(`/api/trips/${tripId}/expenses`),
  create: (tripId: string, data: ExpenseWriteData) =>
    post<{ id: string; ok: boolean }>(`/api/trips/${tripId}/expenses`, data),
  update: (tripId: string, expenseId: string, data: Partial<ExpenseWriteData>) =>
    patch<{ ok: boolean }>(`/api/trips/${tripId}/expenses/${expenseId}`, data),
  delete: (tripId: string, expenseId: string) =>
    del<null>(`/api/trips/${tripId}/expenses/${expenseId}`),
  participants: (tripId: string) =>
    get<Participant[]>(`/api/trips/${tripId}/expenses/participants`),
  balances: (tripId: string) => get<Balances>(`/api/trips/${tripId}/expenses/balances`),
};

export interface SegmentPlaceInput {
  name: string;
  lat?: number | null;
  lon?: number | null;
  country_code?: string | null;
}

export interface SegmentWriteData {
  type: SegmentType;
  departure: SegmentPlaceInput;
  arrival: SegmentPlaceInput;
  /** Naive local time at the respective station ("2026-10-04T08:00"); the
   * backend converts to UTC using each station's own timezone. */
  departure_datetime: string;
  arrival_datetime: string;
  operator?: string | null;
  number?: string | null;
  booking_reference?: string | null;
  seat?: string | null;
  notes?: string | null;
}

export const segmentsApi = {
  list: (tripId: string) => get<TripSegment[]>(`/api/trips/${tripId}/segments`),
  create: (tripId: string, data: SegmentWriteData) =>
    post<{ id: string; ok: boolean }>(`/api/trips/${tripId}/segments`, data),
  update: (tripId: string, segmentId: string, data: Partial<SegmentWriteData>) =>
    patch<{ ok: boolean }>(`/api/trips/${tripId}/segments/${segmentId}`, data),
  delete: (tripId: string, segmentId: string) =>
    del<null>(`/api/trips/${tripId}/segments/${segmentId}`),
};

export interface StayPlaceInput {
  name: string;
  address?: string | null;
  lat?: number | null;
  lon?: number | null;
  country_code?: string | null;
}

export interface StayWriteData {
  kind: StayKind;
  place: StayPlaceInput;
  /** Naive local time at the property ("2026-10-04T15:00"); the backend
   * converts to UTC and records the local calendar date alongside it. */
  check_in_datetime: string;
  check_out_datetime: string;
  booking_reference?: string | null;
  confirmation?: string | null;
  contact?: string | null;
  room_type?: string | null;
  guests?: number | null;
  notes?: string | null;
}

export const staysApi = {
  list: (tripId: string) => get<TripStay[]>(`/api/trips/${tripId}/stays`),
  create: (tripId: string, data: StayWriteData) =>
    post<{ id: string; ok: boolean }>(`/api/trips/${tripId}/stays`, data),
  update: (tripId: string, stayId: string, data: Partial<StayWriteData>) =>
    patch<{ ok: boolean }>(`/api/trips/${tripId}/stays/${stayId}`, data),
  delete: (tripId: string, stayId: string) => del<null>(`/api/trips/${tripId}/stays/${stayId}`),
};

export const stationsApi = {
  search: (q: string, kind?: string) =>
    get<StationResult[]>(
      `/api/stations/search?q=${encodeURIComponent(q)}${kind ? `&kind=${kind}` : ''}`,
    ),
};

/** Accommodation and street addresses, for the stay picker. Separate from
 * stationsApi because the station search is tag-filtered to stations — a hotel
 * reaching it would land in the train-station dropdown. */
export const placesApi = {
  search: (q: string) => get<PlaceResult[]>(`/api/places/search?q=${encodeURIComponent(q)}`),
};

/** Cities, towns and villages — a trip's own ends. Separate from placesApi
 * because that one is tag-filtered to accommodation and addresses: a city
 * reaching it would come back as a street. */
export const citiesApi = {
  search: (q: string) => get<PlaceResult[]>(`/api/cities/search?q=${encodeURIComponent(q)}`),
};

export const guestsApi = {
  list: () => get<Guest[]>('/api/guests'),
  create: (name: string) => post<{ id: number; ok: boolean }>('/api/guests', { name }),
  update: (guestId: number, name: string) => patch<Guest>(`/api/guests/${guestId}`, { name }),
  delete: (guestId: number) => del<null>(`/api/guests/${guestId}`),
};

export interface NonFlightDomain {
  domain: string;
  note: string;
  created_at: string;
}

export const packingApi = {
  list: (tripId: string) => get<PackingItem[]>(`/api/trips/${tripId}/packing`),
  create: (tripId: string, text: string) =>
    post<{ id: string; ok: boolean }>(`/api/trips/${tripId}/packing`, { text }),
  update: (tripId: string, itemId: string, data: { text?: string; checked?: boolean }) =>
    patch<{ ok: boolean }>(`/api/trips/${tripId}/packing/${itemId}`, data),
  delete: (tripId: string, itemId: string) =>
    del<null>(`/api/trips/${tripId}/packing/${itemId}`),
  clearChecked: (tripId: string) =>
    post<null>(`/api/trips/${tripId}/packing/clear-checked`),
};

export const nonFlightDomainsApi = {
  list: () => get<NonFlightDomain[]>('/api/settings/admin/non-flight-domains'),
  add: (domain: string, note: string = '') => _request<{ domain: string }>('POST', '/api/settings/admin/non-flight-domains', { domain, note }),
  delete: (domain: string) => del<null>(`/api/settings/admin/non-flight-domains/${encodeURIComponent(domain)}`),
};

export const integrationsApi = {
  list: () => get<IntegrationStatus[]>('/api/settings/admin/integrations'),
};

export const versionApi = {
  get: () => get<VersionInfo>('/api/version'),
};

export const settingsApi = {
  get: () => get<Settings>('/api/settings'),
  update: (data: SettingsUpdatePayload) => post<Settings>('/api/settings', data),
  testImap: (data: { imap_host?: string; imap_port?: number; gmail_address?: string; gmail_app_password?: string }) =>
    post<{ ok: boolean; message: string }>('/api/settings/test-imap', data),
  testImmich: () => post<{ ok: boolean; message: string }>('/api/settings/test-immich'),
  airportCount: () => get<AirportCountResponse>('/api/settings/airports/count'),
  reloadAirports: () => post<AirportCountResponse>('/api/settings/airports/reload'),
};
