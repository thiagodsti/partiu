/**
 * API client — fetch() wrappers for all /api/* endpoints.
 * All functions return plain JS objects/arrays or throw on error.
 */

const BASE = '';  // Same origin

async function _request(method, path, body = null) {
  const opts = {
    method,
    headers: {},
  };
  if (body !== null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(BASE + path, opts);

  if (res.status === 204) return null;

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const message = data.detail || data.error || data.message || `HTTP ${res.status}`;
    throw new Error(message);
  }

  return data;
}

const get = (path) => _request('GET', path);
const post = (path, body) => _request('POST', path, body);
const patch = (path, body) => _request('PATCH', path, body);
const del = (path) => _request('DELETE', path);

// ---- Trips ----

export const trips = {
  list: () => get('/api/trips'),
  get: (id) => get(`/api/trips/${id}`),
  create: (data) => post('/api/trips', data),
  update: (id, data) => patch(`/api/trips/${id}`, data),
  delete: (id) => del(`/api/trips/${id}`),
  addFlight: (tripId, flightId) => post(`/api/trips/${tripId}/flights/${flightId}`),
  removeFlight: (tripId, flightId) => del(`/api/trips/${tripId}/flights/${flightId}`),
};

// ---- Flights ----

export const flights = {
  list: (params = {}) => {
    const qs = new URLSearchParams();
    if (params.tripId) qs.set('trip_id', params.tripId);
    if (params.status) qs.set('status', params.status);
    if (params.limit) qs.set('limit', params.limit);
    if (params.offset) qs.set('offset', params.offset);
    const q = qs.toString() ? `?${qs}` : '';
    return get(`/api/flights${q}`);
  },
  get: (id) => get(`/api/flights/${id}`),
  aircraft: (id) => get(`/api/flights/${id}/aircraft`),
  email: (id) => get(`/api/flights/${id}/email`),
  create: (data) => post('/api/flights', data),
  update: (id, data) => patch(`/api/flights/${id}`, data),
  delete: (id) => del(`/api/flights/${id}`),
};

// ---- Sync ----

export const sync = {
  status: () => get('/api/sync/status'),
  now: () => post('/api/sync/now'),
  cached: () => post('/api/sync/cached'),
  regroup: () => post('/api/sync/regroup'),
  resetAndSync: () => post('/api/sync/reset-and-sync'),
};

// ---- Airports ----

export const airports = {
  get: (iata) => get(`/api/airports/${iata}`),
};

// ---- Settings ----

export const settings = {
  get: () => get('/api/settings'),
  update: (data) => post('/api/settings', data),
  airportCount: () => get('/api/settings/airports/count'),
  reloadAirports: () => post('/api/settings/airports/reload'),
};
