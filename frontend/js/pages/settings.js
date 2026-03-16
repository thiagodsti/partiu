/**
 * Settings Page — Gmail credentials, sync controls, airport data.
 */

import { settings, sync } from '../api.js';

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(iso) {
  if (!iso) return 'Never';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default class SettingsPage {
  constructor(container) {
    this.container = container;
    this._syncPollInterval = null;
  }

  async mount() {
    this.render(`
      <nav class="top-nav">
        <span class="nav-title">⚙ Settings</span>
      </nav>
      <div class="main-content">
        <div class="loading-screen">
          <div class="loading-icon">⚙</div>
          <p>Loading settings...</p>
        </div>
      </div>
    `);

    try {
      const [currentSettings, syncStatus, airportData] = await Promise.all([
        settings.get(),
        sync.status().catch(() => null),
        settings.airportCount().catch(() => null),
      ]);

      this.currentSettings = currentSettings;
      this.syncStatus = syncStatus;
      this.airportCount = airportData?.count || 0;
      this.renderPage();
      this.bindEvents();
    } catch (err) {
      this.render(`
        <nav class="top-nav">
          <span class="nav-title">⚙ Settings</span>
        </nav>
        <div class="main-content">
          <div class="empty-state">
            <div class="empty-state-icon">⚠️</div>
            <div class="empty-state-title">Failed to load settings</div>
            <div class="empty-state-desc">${escapeHtml(err.message)}</div>
          </div>
        </div>
      `);
    }
  }

  renderPage() {
    const s = this.currentSettings || {};
    const status = this.syncStatus || {};
    const running = status.status === 'running';
    const hasError = status.status === 'error';

    const syncStatusHtml = `
      <div class="sync-status-bar" style="margin-bottom:var(--space-md)">
        <span class="sync-dot ${running ? 'running' : hasError ? 'error' : 'idle'}"></span>
        <div>
          <div>${running ? 'Syncing...' : hasError ? 'Sync error' : 'Ready'}</div>
          <div style="font-size:0.75rem;color:var(--text-muted)">
            Last sync: ${formatDate(status.last_synced_at)}
          </div>
          ${hasError ? `<div style="font-size:0.75rem;color:var(--danger)">${escapeHtml(status.last_error || '')}</div>` : ''}
        </div>
        <span style="flex:1"></span>
        <button class="btn btn-primary" id="sync-now-btn" ${running ? 'disabled' : ''} style="padding:6px 16px">
          ${running ? '<span class="spinner"></span> Syncing...' : '↻ Sync Now'}
        </button>
      </div>
    `;

    this.render(`
      <nav class="top-nav">
        <span class="nav-title">⚙ Settings</span>
      </nav>
      <div class="main-content">

        <div class="settings-section">
          <div class="settings-section-title">Sync Status</div>
          ${syncStatusHtml}
          <button class="btn btn-secondary btn-full" id="sync-cached-btn" ${running ? 'disabled' : ''} style="margin-top:var(--space-sm)">
            ⚡ Quick Sync (use cached emails)
          </button>
          <button class="btn btn-secondary btn-full" id="regroup-btn" style="margin-top:var(--space-sm)">
            ⟳ Re-group All Flights
          </button>
          <button class="btn btn-secondary btn-full" id="reset-sync-btn" style="margin-top:var(--space-sm);border-color:var(--danger);color:var(--danger)">
            ⚠ Reset Data & Re-sync from Cache
          </button>
        </div>

        <div class="settings-section">
          <div class="settings-section-title">Gmail Account</div>

          <form id="settings-form">
            <div class="form-group">
              <label class="form-label" for="gmail-address">Gmail Address</label>
              <input
                class="form-input"
                id="gmail-address"
                type="email"
                name="gmail_address"
                placeholder="you@gmail.com"
                value="${escapeHtml(s.gmail_address || '')}"
                autocomplete="email"
              />
            </div>

            <div class="form-group">
              <label class="form-label" for="app-password">App Password</label>
              <input
                class="form-input"
                id="app-password"
                type="password"
                name="gmail_app_password"
                placeholder="${s.gmail_app_password_set ? '(already set — paste to change)' : 'xxxx-xxxx-xxxx-xxxx'}"
                autocomplete="current-password"
              />
              <div class="form-hint">
                Generate at: Google Account → Security → 2-Step Verification → App passwords.
                Use <strong>Mail</strong> + <strong>Other (Partiu)</strong>.
              </div>
            </div>

            <div class="form-group">
              <label class="form-label" for="sync-interval">Sync Interval (minutes)</label>
              <input
                class="form-input"
                id="sync-interval"
                type="number"
                name="sync_interval_minutes"
                min="1"
                max="1440"
                value="${s.sync_interval_minutes || 10}"
              />
            </div>

            <div id="settings-msg" style="min-height:24px;margin-bottom:var(--space-sm)"></div>

            <button class="btn btn-primary btn-full" type="submit" id="save-btn">
              Save Settings
            </button>
          </form>
        </div>

        <div class="settings-section">
          <div class="settings-section-title">Airport Data</div>
          <div style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)">
            ${this.airportCount > 0
              ? `${this.airportCount.toLocaleString()} airports loaded.`
              : `No airports loaded. Download <code>airports.csv</code> from <a href="https://ourairports.com/data/airports.csv" target="_blank">ourairports.com</a> and place it in the <code>data/</code> directory.`
            }
          </div>
          ${this.airportCount > 0 ? `
            <button class="btn btn-secondary" id="reload-airports-btn">
              ↺ Reload Airports
            </button>
          ` : ''}
        </div>

        <div class="settings-section">
          <div class="settings-section-title">About</div>
          <div style="font-size:0.875rem;color:var(--text-secondary)">
            <p>Partiu — Personal flight tracker PWA</p>
            <p style="margin-top:var(--space-sm)">
              Reads Gmail for airline confirmation emails from LATAM, SAS, Norwegian,
              Lufthansa, Azul, and more. Parses them automatically every
              ${s.sync_interval_minutes || 10} minutes.
            </p>
            <p style="margin-top:var(--space-sm)">
              IMAP Host: <code>${escapeHtml(s.imap_host || 'imap.gmail.com')}</code> :
              ${s.imap_port || 993}
            </p>
          </div>
        </div>

      </div>
    `);
  }

  bindEvents() {
    // Sync Now
    const syncBtn = document.getElementById('sync-now-btn');
    if (syncBtn) {
      syncBtn.addEventListener('click', async () => {
        syncBtn.disabled = true;
        syncBtn.innerHTML = '<span class="spinner"></span> Starting...';
        try {
          await sync.now();
          this.showMsg('Sync started!', 'success');
          this.startSyncPoll();
        } catch (err) {
          this.showMsg(`Sync failed: ${err.message}`, 'error');
          syncBtn.disabled = false;
          syncBtn.textContent = '↻ Sync Now';
        }
      });
    }

    // Quick Sync (cached)
    const cachedBtn = document.getElementById('sync-cached-btn');
    if (cachedBtn) {
      cachedBtn.addEventListener('click', async () => {
        cachedBtn.disabled = true;
        cachedBtn.innerHTML = '<span class="spinner"></span> Syncing from cache...';
        try {
          await sync.cached();
          this.showMsg('Cached sync started!', 'success');
          this.startSyncPoll();
        } catch (err) {
          this.showMsg(`Cached sync failed: ${err.message}`, 'error');
          cachedBtn.disabled = false;
          cachedBtn.textContent = '⚡ Quick Sync (use cached emails)';
        }
      });
    }

    // Reset & Re-sync
    const resetSyncBtn = document.getElementById('reset-sync-btn');
    if (resetSyncBtn) {
      resetSyncBtn.addEventListener('click', async () => {
        if (!confirm('This will delete ALL synced flights and trips, then re-process from the email cache. Continue?')) return;
        resetSyncBtn.disabled = true;
        resetSyncBtn.textContent = 'Resetting...';
        try {
          await sync.resetAndSync();
          this.showMsg('Reset done! Re-syncing from cache...', 'success');
          this.startSyncPoll();
        } catch (err) {
          this.showMsg(`Reset failed: ${err.message}`, 'error');
          resetSyncBtn.disabled = false;
          resetSyncBtn.textContent = '⚠ Reset Data & Re-sync from Cache';
        }
      });
    }

    // Regroup
    const regroupBtn = document.getElementById('regroup-btn');
    if (regroupBtn) {
      regroupBtn.addEventListener('click', async () => {
        regroupBtn.disabled = true;
        regroupBtn.textContent = 'Re-grouping...';
        try {
          await sync.regroup();
          this.showMsg('Re-grouping started in background', 'success');
        } catch (err) {
          this.showMsg(`Error: ${err.message}`, 'error');
        } finally {
          regroupBtn.disabled = false;
          regroupBtn.textContent = '⟳ Re-group All Flights';
        }
      });
    }

    // Settings Form
    const form = document.getElementById('settings-form');
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const saveBtn = document.getElementById('save-btn');
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';

        const data = {};
        const addr = document.getElementById('gmail-address').value.trim();
        const pwd = document.getElementById('app-password').value;
        const interval = parseInt(document.getElementById('sync-interval').value);

        if (addr) data.gmail_address = addr;
        if (pwd) data.gmail_app_password = pwd;
        if (!isNaN(interval) && interval > 0) data.sync_interval_minutes = interval;

        try {
          await settings.update(data);
          this.showMsg('Settings saved!', 'success');
          // Clear password field after save
          document.getElementById('app-password').value = '';
        } catch (err) {
          this.showMsg(`Error: ${err.message}`, 'error');
        } finally {
          saveBtn.disabled = false;
          saveBtn.textContent = 'Save Settings';
        }
      });
    }

    // Reload airports
    const reloadBtn = document.getElementById('reload-airports-btn');
    if (reloadBtn) {
      reloadBtn.addEventListener('click', async () => {
        reloadBtn.disabled = true;
        reloadBtn.textContent = 'Reloading...';
        try {
          const result = await settings.reloadAirports();
          this.airportCount = result.count;
          this.showMsg(`Loaded ${result.count.toLocaleString()} airports`, 'success');
          this.renderPage();
          this.bindEvents();
        } catch (err) {
          this.showMsg(`Error: ${err.message}`, 'error');
          reloadBtn.disabled = false;
          reloadBtn.textContent = '↺ Reload Airports';
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

        if (status.status !== 'running' || polls > 60) {
          this.stopSyncPoll();
          this.renderPage();
          this.bindEvents();
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

  showMsg(msg, type = 'info') {
    const el = document.getElementById('settings-msg');
    if (el) {
      el.textContent = msg;
      el.style.color = type === 'success' ? 'var(--success)' :
        type === 'error' ? 'var(--danger)' : 'var(--text-secondary)';
    }
  }

  render(html) {
    this.container.innerHTML = html;
  }

  unmount() {
    this.stopSyncPoll();
  }
}
