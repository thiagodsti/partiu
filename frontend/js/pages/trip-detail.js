/**
 * Trip Detail Page — shows trip header + flight list.
 */

import { trips } from '../api.js';

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDateTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso.slice(0, 16).replace('T', ' ');
  }
}

function formatTime(iso, timezone) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const opts = { hour: '2-digit', minute: '2-digit', hour12: false };
    if (timezone) opts.timeZone = timezone;
    return d.toLocaleTimeString('en-GB', opts);
  } catch {
    return iso.slice(11, 16);
  }
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso.slice(0, 10);
  }
}

function formatDateRange(start, end) {
  if (!start) return '';
  if (!end || end === start) return formatDate(start);
  return `${formatDate(start)} – ${formatDate(end)}`;
}

function formatDuration(minutes) {
  if (!minutes) return '';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function statusBadge(status) {
  const label = status === 'completed' ? 'Completed' :
    status === 'cancelled' ? 'Cancelled' : 'Upcoming';
  return `<span class="badge badge-${status || 'upcoming'}">${label}</span>`;
}

function airlineBadge(code) {
  if (!code) return '';
  return `<span class="airline-badge airline-${code}">${code}</span>`;
}

function renderFlightRow(f) {
  const status = flightStatus(f);
  const statusBadge = status === 'completed'
    ? '<span class="flight-status-badge flight-status-completed">✓</span>'
    : status === 'active'
      ? '<span class="flight-status-badge flight-status-active">● In flight</span>'
      : '';
  return `
    <a class="flight-row flight-row-${status}" href="#/trips/${f.trip_id}/flights/${f.id}">
      <div class="flight-row-route" style="flex:1">
        <div class="flight-route">
          <span>${escapeHtml(f.departure_airport)}</span>
          <span class="flight-route-arrow">→</span>
          <span>${escapeHtml(f.arrival_airport)}</span>
        </div>
        <div class="flight-time">
          ${formatTime(f.departure_datetime, f.departure_timezone)} → ${formatTime(f.arrival_datetime, f.arrival_timezone)}
          <span style="color:var(--text-muted);margin-left:4px">${formatDate(f.departure_datetime)}</span>
        </div>
      </div>
      <div class="flight-meta">
        ${airlineBadge(f.airline_code)}
        <div style="margin-top:4px">${escapeHtml(f.flight_number)}</div>
        ${f.duration_minutes ? `<div style="color:var(--text-muted)">${formatDuration(f.duration_minutes)}</div>` : ''}
        ${statusBadge}
      </div>
    </a>
  `;
}

function legStats(flights) {
  const flyingMinutes = flights.reduce((sum, f) => sum + (f.duration_minutes || 0), 0);

  // Total elapsed = first departure → last arrival.
  // Only shown when no single connection exceeds 24h — beyond that the total
  // becomes misleading (e.g. a 3-day stopover would make it look like a 70h flight).
  let totalMinutes = 0;
  const MAX_STOPOVER_MS = 24 * 60 * 60 * 1000;
  let hasLongStopover = false;

  for (let i = 1; i < flights.length; i++) {
    const prev = new Date(flights[i - 1].arrival_datetime || flights[i - 1].departure_datetime);
    const curr = new Date(flights[i].departure_datetime);
    if (curr - prev > MAX_STOPOVER_MS) { hasLongStopover = true; break; }
  }

  if (!hasLongStopover && flights.length > 0) {
    const first = flights[0];
    const last = flights[flights.length - 1];
    if (first.departure_datetime && last.arrival_datetime) {
      const ms = new Date(last.arrival_datetime) - new Date(first.departure_datetime);
      totalMinutes = Math.round(ms / 60000);
    }
  }

  return { flyingMinutes, totalMinutes };
}

function flightStatus(f) {
  const now = Date.now();
  if (f.arrival_datetime && new Date(f.arrival_datetime).getTime() < now) return 'completed';
  if (f.departure_datetime && new Date(f.departure_datetime).getTime() < now) return 'active';
  return 'upcoming';
}

function legDivider(label, flights) {
  const { flyingMinutes, totalMinutes } = legStats(flights);
  let info = '';
  if (flyingMinutes > 0) {
    info += ` · ${formatDuration(flyingMinutes)} flying`;
    if (totalMinutes > flyingMinutes) {
      info += ` · ${formatDuration(totalMinutes)} total`;
    }
  }
  return `
    <div class="section-divider" style="margin-top:var(--space-lg)">
      <div class="section-divider-line"></div>
      <span class="section-divider-label">${label}${escapeHtml(info)}</span>
      <div class="section-divider-line"></div>
    </div>
  `;
}

function splitLegs(flights, trip) {
  if (flights.length < 2 || trip.origin_airport === trip.destination_airport) {
    return { outbound: flights, returning: null };
  }

  let maxGap = 0;
  let returnIndex = -1;

  for (let i = 1; i < flights.length; i++) {
    const prev = new Date(flights[i - 1].arrival_datetime || flights[i - 1].departure_datetime).getTime();
    const curr = new Date(flights[i].departure_datetime).getTime();
    const gap = curr - prev;
    if (gap > maxGap) {
      maxGap = gap;
      returnIndex = i;
    }
  }

  const TWELVE_HOURS = 12 * 60 * 60 * 1000;
  if (returnIndex > 0 && maxGap >= TWELVE_HOURS) {
    return { outbound: flights.slice(0, returnIndex), returning: flights.slice(returnIndex) };
  }

  return { outbound: flights, returning: null };
}

function dateDivider(nextFlight) {
  const dep = nextFlight.departure_datetime;
  if (!dep) return '';
  const d = new Date(dep);
  const tz = nextFlight.departure_timezone;
  let label;
  try {
    label = d.toLocaleDateString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric',
      ...(tz ? { timeZone: tz } : {}),
    });
  } catch {
    label = dep.slice(0, 10);
  }
  return `
    <div class="date-divider">
      <div class="date-divider-line"></div>
      <span class="date-divider-label">${label}</span>
      <div class="date-divider-line"></div>
    </div>
  `;
}

function connectionBadge(prev, next) {
  if (!prev.arrival_datetime || !next.departure_datetime) return '';
  const gapMs = new Date(next.departure_datetime) - new Date(prev.arrival_datetime);
  if (gapMs <= 0) return '';
  const gapMin = Math.round(gapMs / 60000);
  const h = Math.floor(gapMin / 60);
  const m = gapMin % 60;
  const label = h > 0 ? `${h}h ${m}m` : `${m}m`;
  const airport = prev.arrival_airport || '';
  return `
    <div class="connection-badge">
      <div class="connection-badge-line"></div>
      <span class="connection-badge-label">⏱ ${label} at ${escapeHtml(airport)}</span>
      <div class="connection-badge-line"></div>
    </div>
  `;
}

function renderFlightList(list) {
  if (list.length === 0) return '';
  let html = '';
  for (let i = 0; i < list.length; i++) {
    html += renderFlightRow(list[i]);
    if (i < list.length - 1) {
      const prevDate = (list[i].arrival_datetime || list[i].departure_datetime || '').slice(0, 10);
      const nextDate = (list[i + 1].departure_datetime || '').slice(0, 10);
      const crossesDay = prevDate && nextDate && prevDate !== nextDate;
      // When the connection crosses into a new day, the date divider is enough —
      // no need to also show "80h 15m at GRU" (redundant information).
      if (crossesDay) {
        html += dateDivider(list[i + 1]);
      } else {
        html += connectionBadge(list[i], list[i + 1]);
      }
    }
  }
  return html;
}

function renderLegsWithDividers(flights, trip) {
  if (flights.length === 0) return '';

  const { outbound, returning } = splitLegs(flights, trip);

  let html = legDivider('Outbound', outbound) + renderFlightList(outbound);

  if (returning) {
    html += legDivider('↩ Return', returning) + renderFlightList(returning);
  }

  return html;
}

export default class TripDetailPage {
  constructor(container, tripId) {
    this.container = container;
    this.tripId = tripId;
  }

  async mount() {
    this.render(`
      <nav class="top-nav">
        <a class="nav-back" href="#/trips">←</a>
        <span class="nav-title">Loading...</span>
      </nav>
      <div class="main-content">
        <div class="loading-screen">
          <div class="loading-icon">✈</div>
          <p>Loading trip...</p>
        </div>
      </div>
    `);

    try {
      const trip = await trips.get(this.tripId);
      this.trip = trip;
      this.renderPage();
    } catch (err) {
      this.render(`
        <nav class="top-nav">
          <a class="nav-back" href="#/trips">←</a>
          <span class="nav-title">Error</span>
        </nav>
        <div class="main-content">
          <div class="empty-state">
            <div class="empty-state-icon">⚠️</div>
            <div class="empty-state-title">Failed to load trip</div>
            <div class="empty-state-desc">${escapeHtml(err.message)}</div>
            <a href="#/trips" class="btn btn-primary">Back to Trips</a>
          </div>
        </div>
      `);
    }
  }

  renderPage() {
    const trip = this.trip;
    const flightList = (trip.flights || []);
    const dateRange = formatDateRange(trip.start_date, trip.end_date);

    // Collect unique airline codes
    const airlines = [...new Set(flightList.map(f => f.airline_code).filter(Boolean))];

    const headerHtml = `
      <div class="trip-header">
        <div class="trip-header-route">${escapeHtml(trip.name)}</div>
        ${dateRange ? `<div class="trip-header-dates">
          <span>📅 ${dateRange}</span>
          <span>✈ ${flightList.length} flight${flightList.length !== 1 ? 's' : ''}</span>
        </div>` : ''}
        <div style="margin-top:var(--space-sm);display:flex;gap:var(--space-xs);flex-wrap:wrap">
          ${airlines.map(a => airlineBadge(a)).join('')}
          ${(trip.booking_refs || []).map(r => `<span class="text-sm text-muted">Ref: ${escapeHtml(r)}</span>`).join('')}
        </div>
      </div>
    `;

    const flightsHtml = flightList.length === 0
      ? `<div class="empty-state">
          <div class="empty-state-icon">✈</div>
          <div class="empty-state-title">No flights in this trip</div>
        </div>`
      : renderLegsWithDividers(flightList, trip);

    this.render(`
      <nav class="top-nav">
        <a class="nav-back" href="#/trips">←</a>
        <span class="nav-title">${escapeHtml(trip.name)}</span>
      </nav>
      <div class="main-content">
        ${headerHtml}
        ${flightsHtml}
      </div>
    `);
  }

  render(html) {
    this.container.innerHTML = html;
  }

  unmount() {}
}
