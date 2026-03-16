/**
 * Trips List Page — shows all trips as cards.
 */

import { trips, sync } from '../api.js';

function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso.slice(0, 10);
  }
}

function formatDateRange(startDate, endDate) {
  if (!startDate) return '';
  const start = formatDate(startDate);
  if (!endDate || endDate === startDate) return start;
  const end = formatDate(endDate);
  return `${start} – ${end}`;
}

function airlineBadge(code) {
  if (!code) return '';
  return `<span class="airline-badge airline-${code}">${code}</span>`;
}

function statusBadge(status) {
  const label = status === 'completed' ? 'Completed' :
    status === 'cancelled' ? 'Cancelled' : 'Upcoming';
  return `<span class="badge badge-${status || 'upcoming'}">${label}</span>`;
}

function inferStatus(trip) {
  if (!trip.end_date) return 'upcoming';
  const end = new Date(trip.end_date);
  return end < new Date() ? 'completed' : 'upcoming';
}

function renderTripCard(trip) {
  const status = inferStatus(trip);
  const dateRange = formatDateRange(trip.start_date, trip.end_date);
  const flightCount = trip.flight_count || 0;
  const refs = (trip.booking_refs || []).join(', ');

  return `
    <a class="card-link" href="#/trips/${trip.id}">
      <article class="card trip-card">
        <div class="trip-card-header">
          <h2 class="trip-card-title">${escapeHtml(trip.name)}</h2>
          ${statusBadge(status)}
        </div>
        ${dateRange ? `<div class="trip-card-meta">
          <span>📅 ${dateRange}</span>
          <span>✈ ${flightCount} flight${flightCount !== 1 ? 's' : ''}</span>
        </div>` : ''}
        <div class="trip-card-footer">
          ${refs ? `<span class="text-sm text-muted">Ref: ${escapeHtml(refs)}</span>` : ''}
        </div>
      </article>
    </a>
  `;
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export default class TripsListPage {
  constructor(container) {
    this.container = container;
    this._syncPollInterval = null;
  }

  async mount() {
    this.render('<div class="main-content"><div class="loading-screen"><div class="loading-icon">✈</div><p>Loading trips...</p></div></div>');

    try {
      const [tripsData, syncStatus] = await Promise.all([
        trips.list(),
        sync.status().catch(() => null),
      ]);

      this.tripsList = tripsData.trips || [];
      this.syncStatus = syncStatus;
      this.renderPage();
      this.bindEvents();
      this.startSyncPoll();
    } catch (err) {
      this.render(`
        <div class="main-content">
          <div class="empty-state">
            <div class="empty-state-icon">⚠️</div>
            <div class="empty-state-title">Failed to load trips</div>
            <div class="empty-state-desc">${escapeHtml(err.message)}</div>
            <button class="btn btn-primary" onclick="location.reload()">Retry</button>
          </div>
        </div>
      `);
    }
  }

  renderPage() {
    const syncStatus = this.syncStatus;
    const running = syncStatus && syncStatus.status === 'running';
    const hasError = syncStatus && syncStatus.status === 'error';
    const lastSynced = syncStatus && syncStatus.last_synced_at;

    const syncBar = `
      <div class="sync-status-bar" id="sync-status-bar">
        <span class="sync-dot ${running ? 'running' : hasError ? 'error' : 'idle'}"></span>
        <span>${running ? 'Syncing emails...' : hasError ? `Sync error: ${escapeHtml(syncStatus.last_error || '')}` : lastSynced ? `Last synced: ${formatDate(lastSynced)}` : 'Never synced'}</span>
        <span style="flex:1"></span>
        <button class="btn btn-secondary text-sm" id="sync-now-btn" style="padding:4px 12px" ${running ? 'disabled' : ''}>
          ${running ? '<span class="spinner"></span>' : '↻ Sync'}
        </button>
      </div>
    `;

    const content = this.tripsList.length === 0
      ? `<div class="empty-state">
          <div class="empty-state-icon">✈</div>
          <div class="empty-state-title">No trips yet</div>
          <div class="empty-state-desc">
            Configure your Gmail in Settings and tap Sync to import your flight confirmations.
          </div>
          <a href="#/settings" class="btn btn-primary">Go to Settings</a>
        </div>`
      : this.tripsList.map(renderTripCard).join('');

    this.render(`
      <nav class="top-nav">
        <span class="nav-title">✈ My Trips</span>
      </nav>
      <div class="main-content">
        ${syncBar}
        ${content}
      </div>
    `);
  }

  bindEvents() {
    const btn = document.getElementById('sync-now-btn');
    if (btn) {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span>';
        try {
          await sync.now();
          this.showToast('Sync started!', 'success');
          this.startSyncPoll();
        } catch (err) {
          this.showToast(`Sync failed: ${err.message}`, 'error');
          btn.disabled = false;
          btn.textContent = '↻ Sync';
        }
      });
    }
  }

  startSyncPoll() {
    this.stopSyncPoll();
    let polls = 0;

    this._syncPollInterval = setInterval(async () => {
      polls++;
      try {
        const status = await sync.status();
        this.syncStatus = status;

        // Update the status bar
        const bar = document.getElementById('sync-status-bar');
        if (bar) {
          const running = status.status === 'running';
          bar.innerHTML = `
            <span class="sync-dot ${running ? 'running' : status.status === 'error' ? 'error' : 'idle'}"></span>
            <span>${running ? 'Syncing...' : status.status === 'error' ? `Error: ${escapeHtml(status.last_error || '')}` : `Last synced: ${formatDate(status.last_synced_at)}`}</span>
            <span style="flex:1"></span>
            <button class="btn btn-secondary text-sm" id="sync-now-btn" style="padding:4px 12px" ${running ? 'disabled' : ''}>
              ${running ? '<span class="spinner"></span>' : '↻ Sync'}
            </button>
          `;
          this.bindEvents();
        }

        // If sync completed, reload trips list
        if (status.status !== 'running' || polls > 60) {
          this.stopSyncPoll();
          if (status.status === 'idle') {
            const data = await trips.list();
            this.tripsList = data.trips || [];
            this.renderPage();
            this.bindEvents();
          }
        }
      } catch {
        this.stopSyncPoll();
      }
    }, 2000);
  }

  stopSyncPoll() {
    if (this._syncPollInterval) {
      clearInterval(this._syncPollInterval);
      this._syncPollInterval = null;
    }
  }

  showToast(msg, type) {
    import('../app.js').then(({ showToast }) => showToast(msg, type));
  }

  render(html) {
    this.container.innerHTML = html;
  }

  unmount() {
    this.stopSyncPoll();
  }
}
