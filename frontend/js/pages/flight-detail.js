/**
 * Flight Detail Page — shows all flight fields, lazily fetches aircraft type.
 */

import { flights, airports } from '../api.js';

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
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

function formatTimezone(iso, timezone) {
  if (!iso || !timezone) return null;
  try {
    const d = new Date(iso);
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: timezone,
      timeZoneName: 'short',
    }).formatToParts(d);
    return parts.find(p => p.type === 'timeZoneName')?.value || null;
  } catch {
    return null;
  }
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
    });
  } catch {
    return iso.slice(0, 10);
  }
}

function formatDuration(minutes) {
  if (!minutes) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function cabinLabel(cls) {
  const map = {
    economy: 'Economy',
    premium_economy: 'Premium Economy',
    business: 'Business',
    first: 'First Class',
  };
  return map[cls] || cls || '—';
}

function renderDetailItem(label, value, mono = false) {
  if (!value) return '';
  return `
    <div class="detail-item">
      <div class="detail-label">${escapeHtml(label)}</div>
      <div class="detail-value ${mono ? 'mono' : ''}">${escapeHtml(String(value))}</div>
    </div>
  `;
}

export default class FlightDetailPage {
  constructor(container, tripId, flightId) {
    this.container = container;
    this.tripId = tripId;
    this.flightId = flightId;
    this.flight = null;
  }

  async mount() {
    this.render(`
      <nav class="top-nav">
        <a class="nav-back" href="#/trips/${this.tripId}">←</a>
        <span class="nav-title">Loading...</span>
      </nav>
      <div class="main-content">
        <div class="loading-screen">
          <div class="loading-icon">✈</div>
          <p>Loading flight...</p>
        </div>
      </div>
    `);

    try {
      this.flight = await flights.get(this.flightId);
      this.renderPage();
      // Lazily fetch aircraft info
      this.fetchAircraftInfo();
    } catch (err) {
      this.render(`
        <nav class="top-nav">
          <a class="nav-back" href="#/trips/${this.tripId}">←</a>
          <span class="nav-title">Error</span>
        </nav>
        <div class="main-content">
          <div class="empty-state">
            <div class="empty-state-icon">⚠️</div>
            <div class="empty-state-title">Failed to load flight</div>
            <div class="empty-state-desc">${escapeHtml(err.message)}</div>
            <a href="#/trips/${this.tripId}" class="btn btn-primary">Back</a>
          </div>
        </div>
      `);
    }
  }

  seatMapUrl() {
    const f = this.flight;
    if (!f.aircraft_type) return null;
    const slug = f.aircraft_type
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
    return `https://flightseatmap.com/aircraft/${slug}-seat-map`;
  }

  renderPage() {
    const f = this.flight;
    const backUrl = this.tripId ? `#/trips/${this.tripId}` : '#/trips';
    const title = `${f.departure_airport || '?'} → ${f.arrival_airport || '?'}`;
    const duration = formatDuration(f.duration_minutes);

    const depDate = formatDate(f.departure_datetime);
    const arrDate = formatDate(f.arrival_datetime);
    const showArrDate = arrDate !== depDate;

    const heroHtml = `
      <div class="flight-detail-hero">
        <div style="display:flex;align-items:center;justify-content:center;gap:var(--space-sm);margin-bottom:var(--space-sm)">
          ${f.airline_code ? `<span class="airline-badge airline-${f.airline_code}">${escapeHtml(f.airline_code)}</span>` : ''}
          <span style="font-size:1.1rem;font-weight:600;font-family:monospace">${escapeHtml(f.flight_number)}</span>
          <span class="badge badge-${f.status || 'upcoming'}">${f.status || 'upcoming'}</span>
        </div>

        <div class="flight-detail-route">
          <div class="flight-detail-airport">
            <div class="airport-code">${escapeHtml(f.departure_airport)}</div>
            <div class="airport-time">${formatTime(f.departure_datetime, f.departure_timezone)}</div>
            <div class="airport-date">${depDate}</div>
            ${f.departure_timezone ? `<div class="airport-date" style="color:var(--text-muted);font-size:0.7rem">${escapeHtml(formatTimezone(f.departure_datetime, f.departure_timezone) || f.departure_timezone)}</div>` : ''}
            ${f.departure_terminal ? `<div class="airport-date">Terminal ${escapeHtml(f.departure_terminal)}</div>` : ''}
            ${f.departure_gate ? `<div class="airport-date">Gate ${escapeHtml(f.departure_gate)}</div>` : ''}
          </div>

          <div class="flight-detail-arrow">
            <div class="flight-detail-arrow-line"></div>
            ${duration ? `<div class="flight-duration">${duration}</div>` : ''}
          </div>

          <div class="flight-detail-airport">
            <div class="airport-code">${escapeHtml(f.arrival_airport)}</div>
            <div class="airport-time">${formatTime(f.arrival_datetime, f.arrival_timezone)}</div>
            <div class="airport-date">${showArrDate ? arrDate : ''}</div>
            ${f.arrival_timezone ? `<div class="airport-date" style="color:var(--text-muted);font-size:0.7rem">${escapeHtml(formatTimezone(f.arrival_datetime, f.arrival_timezone) || f.arrival_timezone)}</div>` : ''}
            ${f.arrival_terminal ? `<div class="airport-date">Terminal ${escapeHtml(f.arrival_terminal)}</div>` : ''}
            ${f.arrival_gate ? `<div class="airport-date">Gate ${escapeHtml(f.arrival_gate)}</div>` : ''}
          </div>
        </div>

        <div id="aircraft-badge-container" style="margin-top:var(--space-md)">
          ${f.aircraft_type ? `
            <div class="aircraft-badge">
              ✈ ${escapeHtml(f.aircraft_type)}
              ${f.aircraft_registration ? `<span style="color:var(--text-muted);font-size:0.75rem">(${escapeHtml(f.aircraft_registration)})</span>` : ''}
            </div>
          ` : (() => {
            const isCompleted = f.arrival_datetime && new Date(f.arrival_datetime).getTime() < Date.now();
            if (isCompleted) {
              return '<span style="color:var(--text-muted);font-size:0.8rem">Aircraft type not available</span>';
            }
            return '<div id="aircraft-loading" style="color:var(--text-muted);font-size:0.8rem">Looking up aircraft...</div>';
          })()}
        </div>
      </div>
    `;

    const detailGrid = `
      <div class="detail-grid">
        ${renderDetailItem('Airline', f.airline_name || f.airline_code)}
        ${renderDetailItem('Flight', f.flight_number, true)}
        ${renderDetailItem('Booking Ref', f.booking_reference, true)}
        ${renderDetailItem('Passenger', f.passenger_name)}
        ${renderDetailItem('Seat', f.seat)}
        ${renderDetailItem('Class', cabinLabel(f.cabin_class))}
        ${renderDetailItem('Duration', duration)}
        ${renderDetailItem('Status', f.status)}
      </div>
    `;

    const emailInfo = f.email_subject ? `
      <div class="detail-grid" style="margin-top:var(--space-sm)">
        <div class="detail-item" style="grid-column:1/-1">
          <div class="detail-label">Email Source</div>
          <div class="detail-value text-sm" style="color:var(--text-muted)">${escapeHtml(f.email_subject || '')}</div>
          ${f.email_date ? `<div class="detail-value text-sm" style="color:var(--text-muted)">${formatDate(f.email_date)}</div>` : ''}
        </div>
      </div>
    ` : '';

    const notesSection = f.notes ? `
      <div class="card" style="margin-top:var(--space-md)">
        <div class="detail-label">Notes</div>
        <div class="detail-value">${escapeHtml(f.notes)}</div>
      </div>
    ` : '';

    this.render(`
      <nav class="top-nav">
        <a class="nav-back" href="${backUrl}">←</a>
        <span class="nav-title">${escapeHtml(title)}</span>
      </nav>
      <div class="main-content">
        ${heroHtml}
        ${detailGrid}
        ${emailInfo}
        ${notesSection}
        <div id="airport-maps-section" style="margin-top:var(--space-md)"></div>
        <div style="margin-top:var(--space-lg);padding-bottom:var(--space-lg);display:flex;flex-direction:column;gap:var(--space-sm)">
          ${this.seatMapUrl() ? `
            <a href="${this.seatMapUrl()}" target="_blank" rel="noopener" class="btn btn-secondary" style="width:100%;text-align:center;text-decoration:none">
              💺 View Seat Map
            </a>
          ` : ''}
          <button class="btn btn-secondary" id="raw-email-btn" style="width:100%">
            📧 View Raw Email
          </button>
        </div>
      </div>
    `);

    document.getElementById('raw-email-btn')?.addEventListener('click', () => {
      this.openRawEmail();
    });

    this.fetchAirportMaps();
  }

  async fetchAirportMaps() {
    const f = this.flight;
    const [dep, arr] = await Promise.all([
      airports.get(f.departure_airport).catch(() => null),
      airports.get(f.arrival_airport).catch(() => null),
    ]);

    const container = document.getElementById('airport-maps-section');
    if (!container || (!dep && !arr)) return;

    const makeMapEntry = (airport, label, btnId, mapId) => {
      if (!airport?.latitude || !airport?.longitude) return '';
      const lat = airport.latitude;
      const lon = airport.longitude;
      const d = 0.009;
      const bbox = `${lon - d},${lat - d},${lon + d},${lat + d}`;
      const embedUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lon}`;
      const name = `${airport.iata_code} — ${airport.name}${airport.city_name ? `, ${airport.city_name}` : ''}`;
      return `
        <button class="btn btn-secondary" id="${btnId}" style="width:100%;text-align:left">
          🗺 ${label} Airport Map — ${escapeHtml(airport.iata_code)}
        </button>
        <div id="${mapId}" style="display:none;margin-top:var(--space-xs)">
          <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:var(--space-xs)">${escapeHtml(name)}</div>
          <iframe
            src="${embedUrl}"
            style="width:100%;height:260px;border:1px solid var(--border);border-radius:var(--radius-md)"
            loading="lazy"
            title="${escapeHtml(airport.name)} map"
          ></iframe>
        </div>
      `;
    };

    container.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:var(--space-sm)">
        ${makeMapEntry(dep, 'Departure', 'dep-map-btn', 'dep-map')}
        ${makeMapEntry(arr, 'Arrival', 'arr-map-btn', 'arr-map')}
      </div>
    `;

    const wire = (btnId, mapId) => {
      const btn = document.getElementById(btnId);
      const map = document.getElementById(mapId);
      if (!btn || !map) return;
      btn.addEventListener('click', () => {
        const open = map.style.display === 'none';
        map.style.display = open ? 'block' : 'none';
        btn.style.opacity = open ? '1' : '0.7';
      });
    };
    wire('dep-map-btn', 'dep-map');
    wire('arr-map-btn', 'arr-map');
  }

  async openRawEmail() {
    const btn = document.getElementById('raw-email-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Loading...'; }
    try {
      const data = await flights.email(this.flightId);
      this.showEmailModal(data);
    } catch (err) {
      alert(`Could not load email: ${err.message}`);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '📧 View Raw Email'; }
    }
  }

  showEmailModal(data) {
    const overlay = document.createElement('div');
    overlay.style.cssText = `
      position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:1000;
      display:flex;flex-direction:column;overflow:hidden;
    `;

    const header = document.createElement('div');
    header.style.cssText = `
      display:flex;align-items:center;justify-content:space-between;
      padding:12px 16px;background:var(--surface);border-bottom:1px solid var(--border);
      flex-shrink:0;
    `;
    header.innerHTML = `
      <div style="font-size:0.85rem;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">
        ${escapeHtml(data.email_subject || 'Raw Email')}
      </div>
      <button id="close-modal-btn" style="
        background:none;border:none;color:var(--text-primary);font-size:1.4rem;
        cursor:pointer;padding:0 0 0 12px;line-height:1;flex-shrink:0;
      ">✕</button>
    `;

    const content = document.createElement('div');
    content.style.cssText = 'flex:1;overflow:auto;';

    if (data.html_body) {
      const iframe = document.createElement('iframe');
      iframe.style.cssText = 'width:100%;height:100%;border:none;background:#fff;';
      iframe.sandbox = 'allow-same-origin';
      content.appendChild(iframe);
      overlay.appendChild(header);
      overlay.appendChild(content);
      document.body.appendChild(overlay);
      iframe.srcdoc = data.html_body;
    } else {
      const pre = document.createElement('pre');
      pre.style.cssText = `
        margin:0;padding:16px;font-size:0.75rem;white-space:pre-wrap;
        word-break:break-all;color:var(--text-primary);
      `;
      pre.textContent = 'No HTML body available for this flight.';
      content.appendChild(pre);
      overlay.appendChild(header);
      overlay.appendChild(content);
      document.body.appendChild(overlay);
    }

    const close = () => document.body.removeChild(overlay);
    header.querySelector('#close-modal-btn').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  }

  async fetchAircraftInfo() {
    const f = this.flight;
    if (f.aircraft_type) return;  // Already cached in DB

    // Completed flights won't be found on OpenSky — the background job handles
    // aircraft lookup while the flight is airborne. Just hide the spinner.
    const isCompleted = f.arrival_datetime && new Date(f.arrival_datetime).getTime() < Date.now();
    if (isCompleted) {
      const loader = document.getElementById('aircraft-loading');
      if (loader) loader.remove();
      return;
    }

    try {
      const info = await flights.aircraft(this.flightId);
      const container = document.getElementById('aircraft-badge-container');
      if (!container) return;

      if (info && info.type_name) {
        container.innerHTML = `
          <div class="aircraft-badge" style="margin-top:var(--space-md)">
            ✈ ${escapeHtml(info.type_name)}
            ${info.registration ? `<span style="color:var(--text-muted);font-size:0.75rem">(${escapeHtml(info.registration)})</span>` : ''}
          </div>
        `;
      } else {
        container.innerHTML = '';
      }
    } catch {
      const loader = document.getElementById('aircraft-loading');
      if (loader) loader.remove();
    }
  }

  render(html) {
    this.container.innerHTML = html;
  }

  unmount() {}
}
