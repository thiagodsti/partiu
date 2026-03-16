<script lang="ts">
  import { onDestroy } from 'svelte';
  import { settingsApi, syncApi } from '../api/client';
  import type { Settings, SyncStatus } from '../api/types';
  import { formatDateTimeLocale } from '../lib/utils';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import TopNav from '../components/TopNav.svelte';

  // ---- State ----
  let loading = $state(true);
  let error = $state<string | null>(null);
  let currentSettings = $state<Settings | null>(null);
  let syncStatus = $state<SyncStatus | null>(null);
  let airportCount = $state(0);

  // Form fields
  let gmailAddress = $state('');
  let appPassword = $state('');
  let syncInterval = $state(10);
  let smtpEnabled = $state(false);
  let smtpPort = $state(2525);
  let smtpRecipient = $state('');
  let smtpAllowedSenders = $state('');

  // UI state
  let savingSettings = $state(false);
  let settingsMsg = $state('');
  let settingsMsgType = $state<'success' | 'error' | 'info'>('info');

  let syncingNow = $state(false);
  let syncingCached = $state(false);
  let regrouping = $state(false);
  let resetting = $state(false);
  let reloadingAirports = $state(false);

  let syncPollInterval: ReturnType<typeof setInterval> | null = null;

  // ---- Load ----
  async function load() {
    loading = true;
    error = null;
    try {
      const [s, status, airportData] = await Promise.all([
        settingsApi.get(),
        syncApi.status().catch(() => null),
        settingsApi.airportCount().catch(() => null),
      ]);
      currentSettings = s;
      syncStatus = status;
      airportCount = airportData?.count ?? 0;
      // Populate form
      gmailAddress = s.gmail_address ?? '';
      syncInterval = s.sync_interval_minutes ?? 10;
      smtpEnabled = s.smtp_server_enabled ?? false;
      smtpPort = s.smtp_server_port ?? 2525;
      smtpRecipient = s.smtp_recipient_address ?? '';
      smtpAllowedSenders = s.smtp_allowed_senders ?? '';
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  // ---- Sync actions ----
  async function syncNow() {
    syncingNow = true;
    try {
      await syncApi.now();
      showMsg('Sync started!', 'success');
      startSyncPoll();
    } catch (err) {
      showMsg(`Sync failed: ${(err as Error).message}`, 'error');
    } finally {
      syncingNow = false;
    }
  }

  async function syncCached() {
    syncingCached = true;
    try {
      await syncApi.cached();
      showMsg('Cached sync started!', 'success');
      startSyncPoll();
    } catch (err) {
      showMsg(`Cached sync failed: ${(err as Error).message}`, 'error');
    } finally {
      syncingCached = false;
    }
  }

  async function regroup() {
    regrouping = true;
    try {
      await syncApi.regroup();
      showMsg('Re-grouping started in background', 'success');
    } catch (err) {
      showMsg(`Error: ${(err as Error).message}`, 'error');
    } finally {
      regrouping = false;
    }
  }

  async function resetAndSync() {
    if (!confirm('This will delete ALL synced flights and trips, then re-process from the email cache. Continue?')) return;
    resetting = true;
    try {
      await syncApi.resetAndSync();
      showMsg('Reset done! Re-syncing from cache...', 'success');
      startSyncPoll();
    } catch (err) {
      showMsg(`Reset failed: ${(err as Error).message}`, 'error');
    } finally {
      resetting = false;
    }
  }

  function startSyncPoll() {
    stopSyncPoll();
    let polls = 0;
    syncPollInterval = setInterval(async () => {
      polls++;
      try {
        const status = await syncApi.status();
        syncStatus = status;
        if (status.status !== 'running' || polls > 60) {
          stopSyncPoll();
        }
      } catch {
        stopSyncPoll();
      }
    }, 2000);
  }

  function stopSyncPoll() {
    if (syncPollInterval) {
      clearInterval(syncPollInterval);
      syncPollInterval = null;
    }
  }

  onDestroy(stopSyncPoll);

  // ---- Settings form ----
  async function saveSettings(e: Event) {
    e.preventDefault();
    savingSettings = true;
    const data: Record<string, unknown> = {};
    if (gmailAddress.trim()) data.gmail_address = gmailAddress.trim();
    if (appPassword) data.gmail_app_password = appPassword;
    if (!isNaN(syncInterval) && syncInterval > 0) data.sync_interval_minutes = syncInterval;
    data.smtp_server_enabled = smtpEnabled;
    data.smtp_server_port = smtpPort;
    data.smtp_recipient_address = smtpRecipient.trim();
    data.smtp_allowed_senders = smtpAllowedSenders.trim();
    try {
      await settingsApi.update(data);
      showMsg('Settings saved!', 'success');
      appPassword = '';
    } catch (err) {
      showMsg(`Error: ${(err as Error).message}`, 'error');
    } finally {
      savingSettings = false;
    }
  }

  // ---- Airport reload ----
  async function reloadAirports() {
    reloadingAirports = true;
    try {
      const result = await settingsApi.reloadAirports();
      airportCount = result?.count ?? 0;
      showMsg(`Loaded ${airportCount.toLocaleString()} airports`, 'success');
    } catch (err) {
      showMsg(`Error: ${(err as Error).message}`, 'error');
    } finally {
      reloadingAirports = false;
    }
  }

  // ---- Msg helper ----
  function showMsg(msg: string, type: 'success' | 'error' | 'info' = 'info') {
    settingsMsg = msg;
    settingsMsgType = type;
  }

  // ---- Derived ----
  const syncRunning = $derived(syncStatus?.status === 'running');
  const syncHasError = $derived(syncStatus?.status === 'error');
  const anySyncRunning = $derived(syncRunning || syncingNow || syncingCached);
</script>

<TopNav title="⚙ Settings" />

<div class="main-content">
  {#if loading}
    <LoadingScreen icon="⚙" message="Loading settings..." />
  {:else if error}
    <EmptyState icon="⚠️" title="Failed to load settings" description={error} />
  {:else}
    <!-- Sync Status Section -->
    <div class="settings-section">
      <div class="settings-section-title">Sync Status</div>
      <div class="sync-status-bar" style="margin-bottom:var(--space-md)">
        <span class="sync-dot {syncRunning ? 'running' : syncHasError ? 'error' : 'idle'}"></span>
        <div>
          <div>{syncRunning ? 'Syncing...' : syncHasError ? 'Sync error' : 'Ready'}</div>
          <div style="font-size:0.75rem;color:var(--text-muted)">
            Last sync: {formatDateTimeLocale(syncStatus?.last_synced_at)}
          </div>
          {#if syncHasError}
            <div style="font-size:0.75rem;color:var(--danger)">{syncStatus?.last_error ?? ''}</div>
          {/if}
        </div>
        <span style="flex:1"></span>
        <button
          class="btn btn-primary"
          disabled={anySyncRunning}
          style="padding:6px 16px"
          onclick={syncNow}
        >
          {#if syncRunning || syncingNow}
            <span class="spinner"></span> Syncing...
          {:else}
            ↻ Sync Now
          {/if}
        </button>
      </div>

      <button
        class="btn btn-secondary btn-full"
        disabled={anySyncRunning}
        style="margin-top:var(--space-sm)"
        onclick={syncCached}
      >
        {#if syncingCached}
          <span class="spinner"></span> Syncing from cache...
        {:else}
          ⚡ Quick Sync (use cached emails)
        {/if}
      </button>

      <button
        class="btn btn-secondary btn-full"
        disabled={regrouping}
        style="margin-top:var(--space-sm)"
        onclick={regroup}
      >
        {regrouping ? 'Re-grouping...' : '⟳ Re-group All Flights'}
      </button>

      <button
        class="btn btn-secondary btn-full"
        disabled={resetting}
        style="margin-top:var(--space-sm);border-color:var(--danger);color:var(--danger)"
        onclick={resetAndSync}
      >
        {resetting ? 'Resetting...' : '⚠ Reset Data & Re-sync from Cache'}
      </button>
    </div>

    <!-- Gmail Account Section -->
    <div class="settings-section">
      <div class="settings-section-title">Gmail Account</div>

      <form onsubmit={saveSettings}>
        <div class="form-group">
          <label class="form-label" for="gmail-address">Gmail Address</label>
          <input
            class="form-input"
            id="gmail-address"
            type="email"
            bind:value={gmailAddress}
            placeholder="you@gmail.com"
            autocomplete="email"
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="app-password">App Password</label>
          <input
            class="form-input"
            id="app-password"
            type="password"
            bind:value={appPassword}
            placeholder={currentSettings?.gmail_app_password_set
              ? '(already set — paste to change)'
              : 'xxxx-xxxx-xxxx-xxxx'}
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
            bind:value={syncInterval}
            min="1"
            max="1440"
          />
        </div>

        {#if settingsMsg}
          <div
            style="min-height:24px;margin-bottom:var(--space-sm);color:{settingsMsgType === 'success' ? 'var(--success)' : settingsMsgType === 'error' ? 'var(--danger)' : 'var(--text-secondary)'}"
          >
            {settingsMsg}
          </div>
        {:else}
          <div style="min-height:24px;margin-bottom:var(--space-sm)"></div>
        {/if}

        <button class="btn btn-primary btn-full" type="submit" disabled={savingSettings}>
          {savingSettings ? 'Saving...' : 'Save Settings'}
        </button>
      </form>
    </div>

    <!-- Inbound SMTP Section -->
    <div class="settings-section">
      <div class="settings-section-title">Inbound Email Server</div>
      <div style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)">
        Run a simple SMTP server so you can forward flight confirmation emails directly to this app.
        Configure your mail client or email alias to forward to <strong>this server's IP</strong> on the port below.
      </div>

      <form onsubmit={saveSettings}>
        <div class="form-group">
          <label class="form-label" style="display:flex;align-items:center;gap:var(--space-sm)">
            <input
              type="checkbox"
              bind:checked={smtpEnabled}
              style="width:auto;margin:0"
            />
            Enable SMTP server
          </label>
        </div>

        {#if smtpEnabled}
          <div class="form-group">
            <label class="form-label" for="smtp-port">Port</label>
            <input
              class="form-input"
              id="smtp-port"
              type="number"
              bind:value={smtpPort}
              min="1"
              max="65535"
              placeholder="2525"
            />
            <div class="form-hint">Use 2525 (or any port above 1024) to avoid needing root. Forward your domain's MX or an alias to this port.</div>
          </div>

          <div class="form-group">
            <label class="form-label" for="smtp-recipient">Accept mail to</label>
            <input
              class="form-input"
              id="smtp-recipient"
              type="email"
              bind:value={smtpRecipient}
              placeholder="trips@your-domain.com"
            />
            <div class="form-hint">Only emails addressed to this recipient will be processed. Leave blank to accept any recipient.</div>
          </div>

          <div class="form-group">
            <label class="form-label" for="smtp-senders">Allowed senders</label>
            <input
              class="form-input"
              id="smtp-senders"
              type="text"
              bind:value={smtpAllowedSenders}
              placeholder="you@gmail.com, partner@gmail.com"
            />
            <div class="form-hint">Comma-separated list of email addresses allowed to send. Leave blank to accept from anyone (less secure).</div>
          </div>
        {/if}

        {#if settingsMsg}
          <div
            style="min-height:24px;margin-bottom:var(--space-sm);color:{settingsMsgType === 'success' ? 'var(--success)' : settingsMsgType === 'error' ? 'var(--danger)' : 'var(--text-secondary)'}"
          >
            {settingsMsg}
          </div>
        {:else}
          <div style="min-height:24px;margin-bottom:var(--space-sm)"></div>
        {/if}

        <button class="btn btn-primary btn-full" type="submit" disabled={savingSettings}>
          {savingSettings ? 'Saving...' : 'Save Settings'}
        </button>
      </form>
    </div>

    <!-- Airport Data Section -->
    <div class="settings-section">
      <div class="settings-section-title">Airport Data</div>
      <div style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)">
        {#if airportCount > 0}
          {airportCount.toLocaleString()} airports loaded.
        {:else}
          No airports loaded. Download <code>airports.csv</code> from
          <a href="https://ourairports.com/data/airports.csv" target="_blank">ourairports.com</a>
          and place it in the <code>data/</code> directory.
        {/if}
      </div>
      {#if airportCount > 0}
        <button
          class="btn btn-secondary"
          disabled={reloadingAirports}
          onclick={reloadAirports}
        >
          {reloadingAirports ? 'Reloading...' : '↺ Reload Airports'}
        </button>
      {/if}
    </div>

    <!-- About Section -->
    <div class="settings-section">
      <div class="settings-section-title">About</div>
      <div style="font-size:0.875rem;color:var(--text-secondary)">
        <p>Partiu — Personal flight tracker PWA</p>
        <p style="margin-top:var(--space-sm)">
          Reads Gmail for airline confirmation emails from LATAM, SAS, Norwegian,
          Lufthansa, Azul, and more. Parses them automatically every
          {currentSettings?.sync_interval_minutes ?? 10} minutes.
        </p>
        <p style="margin-top:var(--space-sm)">
          IMAP Host: <code>{currentSettings?.imap_host ?? 'imap.gmail.com'}</code> :
          {currentSettings?.imap_port ?? 993}
        </p>
      </div>
    </div>
  {/if}
</div>
