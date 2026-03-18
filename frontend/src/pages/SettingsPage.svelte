<script lang="ts">
  import { onDestroy } from "svelte";
  import QRCode from "qrcode";
  import { settingsApi, syncApi, authApi } from "../api/client";
  import type { Settings, SyncStatus } from "../api/types";
  import { formatDateTimeLocale } from "../lib/utils";
  import LoadingScreen from "../components/LoadingScreen.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import TopNav from "../components/TopNav.svelte";
  import { currentUser } from "../lib/authStore";
  import { theme } from "../lib/themeStore";
  import { t, locale, setLocale, LOCALES } from "../lib/i18n";

  // ---- State ----
  let loading = $state(true);
  let error = $state<string | null>(null);
  let currentSettings = $state<Settings | null>(null);
  let syncStatus = $state<SyncStatus | null>(null);
  let airportCount = $state(0);

  const IMAP_PRESETS = [
    { label: "Gmail", host: "imap.gmail.com", port: 993 },
    { label: "Outlook", host: "outlook.office365.com", port: 993 },
    { label: "Zoho", host: "imap.zoho.com", port: 993 },
    { label: "Yahoo", host: "imap.mail.yahoo.com", port: 993 },
  ];

  // Form fields
  let gmailAddress = $state("");
  let appPassword = $state("");
  let imapHost = $state("imap.gmail.com");
  let imapPort = $state(993);

  const imapPreset = $derived(
    IMAP_PRESETS.find((p) => p.host === imapHost && p.port === imapPort)
      ?.label ?? "custom",
  );

  function applyImapPreset(label: string) {
    const preset = IMAP_PRESETS.find((p) => p.label === label);
    if (preset) {
      imapHost = preset.host;
      imapPort = preset.port;
    }
  }
  let syncInterval = $state(10);
  let maxEmailsPerSync = $state(200);
  let firstSyncDays = $state(90);
  let smtpEnabled = $state(false);
  let smtpPort = $state(2525);
  let smtpDomain = $state("");
  let smtpRecipient = $state("");
  let smtpAllowedSenders = $state("");

  // UI state
  let savingSettings = $state(false);
  let settingsMsg = $state("");
  let settingsMsgType = $state<"success" | "error" | "info">("info");

  let testingImap = $state(false);
  let imapTestMsg = $state("");
  let imapTestOk = $state(false);

  let regrouping = $state(false);
  let resetting = $state(false);
  let resetConfirmStep = $state(false);
  let resetConfirmText = $state("");
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
      gmailAddress = s.gmail_address ?? "";
      imapHost = s.imap_host ?? "imap.gmail.com";
      imapPort = s.imap_port ?? 993;
      syncInterval = s.sync_interval_minutes ?? 10;
      maxEmailsPerSync = s.max_emails_per_sync ?? 200;
      firstSyncDays = s.first_sync_days ?? 90;
      smtpEnabled = s.smtp_server_enabled ?? false;
      smtpPort = s.smtp_server_port ?? 2525;
      smtpDomain = s.smtp_domain ?? "";
      smtpRecipient =
        s.smtp_recipient_address ||
        (s.smtp_domain && $currentUser
          ? `${$currentUser.username}@${s.smtp_domain}`
          : "");
      smtpAllowedSenders = s.smtp_allowed_senders ?? "";
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  // ---- Sync actions ----
  async function regroup() {
    regrouping = true;
    try {
      await syncApi.regroup();
      showMsg($t("settings.regroup_ok"), "success");
    } catch (err) {
      showMsg(`Error: ${(err as Error).message}`, "error");
    } finally {
      regrouping = false;
    }
  }

  async function resetAndSync() {
    if (resetConfirmText !== "RESET") return;
    resetConfirmStep = false;
    resetConfirmText = "";
    resetting = true;
    try {
      await syncApi.resetAndSync();
      showMsg("Reset done! Re-syncing from email...", "success");
      startSyncPoll();
    } catch (err) {
      showMsg(`Reset failed: ${(err as Error).message}`, "error");
    } finally {
      resetting = false;
    }
  }

  function cancelReset() {
    resetConfirmStep = false;
    resetConfirmText = "";
  }

  function startSyncPoll() {
    stopSyncPoll();
    let polls = 0;
    syncPollInterval = setInterval(async () => {
      polls++;
      try {
        const status = await syncApi.status();
        syncStatus = status;
        if (status.status !== "running" || polls > 60) {
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
    data.imap_host = imapHost.trim();
    data.imap_port = imapPort;
    if ($currentUser?.is_admin) {
      if (!isNaN(syncInterval) && syncInterval > 0)
        data.sync_interval_minutes = syncInterval;
      if (!isNaN(maxEmailsPerSync) && maxEmailsPerSync > 0)
        data.max_emails_per_sync = maxEmailsPerSync;
      if (!isNaN(firstSyncDays) && firstSyncDays > 0)
        data.first_sync_days = firstSyncDays;
      data.smtp_server_enabled = smtpEnabled;
      data.smtp_server_port = smtpPort;
      data.smtp_domain = smtpDomain.trim();
    }
    data.smtp_recipient_address = smtpRecipient.trim();
    data.smtp_allowed_senders = smtpAllowedSenders.trim();
    try {
      await settingsApi.update(data);
      showMsg($t("settings.saved"), "success");
      appPassword = "";
    } catch (err) {
      showMsg(`Error: ${(err as Error).message}`, "error");
    } finally {
      savingSettings = false;
    }
  }

  // ---- IMAP test ----
  async function testImapConnection() {
    testingImap = true;
    imapTestMsg = "";
    try {
      const result = await settingsApi.testImap({
        imap_host: imapHost.trim(),
        imap_port: imapPort,
        gmail_address: gmailAddress.trim() || undefined,
        gmail_app_password: appPassword || undefined,
      });
      imapTestMsg = result.message;
      imapTestOk = true;
    } catch (err) {
      imapTestMsg = (err as Error).message;
      imapTestOk = false;
    } finally {
      testingImap = false;
    }
  }

  // ---- Airport reload ----
  async function reloadAirports() {
    reloadingAirports = true;
    try {
      const result = await settingsApi.reloadAirports();
      airportCount = result?.count ?? 0;
      showMsg(
        $t("settings.airports_loaded", {
          values: { n: airportCount.toLocaleString() },
        }),
        "success",
      );
    } catch (err) {
      showMsg(`Error: ${(err as Error).message}`, "error");
    } finally {
      reloadingAirports = false;
    }
  }

  // ---- Msg helper ----
  function showMsg(msg: string, type: "success" | "error" | "info" = "info") {
    settingsMsg = msg;
    settingsMsgType = type;
  }

  // ---- Change password ----
  let currentPw = $state("");
  let newPw = $state("");
  let pwTotpCode = $state("");
  let changingPw = $state(false);
  let pwMsg = $state("");
  let pwMsgType = $state<"success" | "error">("success");

  async function changePassword(e: Event) {
    e.preventDefault();
    if (!currentPw || !newPw) return;
    changingPw = true;
    pwMsg = "";
    try {
      const payload: {
        current_password: string;
        new_password: string;
        totp_code?: string;
      } = {
        current_password: currentPw,
        new_password: newPw,
      };
      if ($currentUser?.totp_enabled) payload.totp_code = pwTotpCode;
      await authApi.changePassword(payload);
      pwMsg = "Password changed successfully";
      pwMsgType = "success";
      currentPw = "";
      newPw = "";
      pwTotpCode = "";
    } catch (err) {
      pwMsg = (err as Error).message;
      pwMsgType = "error";
    } finally {
      changingPw = false;
    }
  }

  // ---- Derived ----
  const syncRunning = $derived(syncStatus?.status === "running");
  const syncHasError = $derived(syncStatus?.status === "error");

  const nextSyncLabel = $derived.by(() => {
    if (!syncStatus?.last_synced_at || !syncStatus?.sync_interval_minutes)
      return null;
    const nextMs =
      new Date(syncStatus.last_synced_at).getTime() +
      syncStatus.sync_interval_minutes * 60 * 1000;
    const nowMs = Date.now();
    if (nextMs <= nowMs) return $t("trips.next_sync_at_any_moment");
    const diffMin = Math.round((nextMs - nowMs) / 60000);
    if (diffMin < 1) return $t("trips.next_sync_at_any_moment");
    const h = Math.floor(diffMin / 60);
    const m = diffMin % 60;
    const rel = h > 0 ? `${h}h ${m}m` : `${m}m`;
    const absTime = new Date(nextMs).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
    return $t("trips.next_sync_at", { values: { rel: rel, absTime: absTime } });
  });

  // ---- 2FA state ----
  // 'idle' | 'setup' | 'enabled' | 'disabling'
  let twoFaState = $derived.by(() => {
    if ($currentUser?.totp_enabled) return "enabled" as const;
    return twoFaSetupActive ? ("setup" as const) : ("idle" as const);
  });

  let twoFaSetupActive = $state(false);
  let twoFaSecret = $state("");
  let twoFaUri = $state("");
  let twoFaQrSvg = $state("");
  let twoFaCode = $state("");
  let twoFaLoading = $state(false);
  let twoFaMsg = $state("");
  let twoFaMsgType = $state<"success" | "error">("success");

  let disablingTwoFa = $state(false);
  let disableCode = $state("");
  let disablePassword = $state("");
  let disableLoading = $state(false);

  async function startSetup2fa() {
    twoFaLoading = true;
    twoFaMsg = "";
    try {
      const data = await authApi.setup2fa();
      twoFaSecret = data.secret;
      twoFaUri = data.uri;
      twoFaQrSvg = await QRCode.toString(data.uri, {
        type: "svg",
        margin: 2,
        errorCorrectionLevel: "M",
        color: { dark: "#000000", light: "#ffffff" },
      });
      twoFaCode = "";
      twoFaSetupActive = true;
    } catch (err) {
      twoFaMsg = (err as Error).message;
      twoFaMsgType = "error";
    } finally {
      twoFaLoading = false;
    }
  }

  async function confirmEnable2fa(e: Event) {
    e.preventDefault();
    if (!twoFaCode || twoFaCode.length !== 6) return;
    twoFaLoading = true;
    twoFaMsg = "";
    try {
      await authApi.enable2fa(twoFaCode);
      // Update local store
      if ($currentUser)
        currentUser.set({ ...$currentUser, totp_enabled: true });
      twoFaSetupActive = false;
      twoFaCode = "";
      twoFaMsg = "2FA enabled successfully";
      twoFaMsgType = "success";
    } catch (err) {
      twoFaMsg = (err as Error).message;
      twoFaMsgType = "error";
    } finally {
      twoFaLoading = false;
    }
  }

  async function confirmDisable2fa(e: Event) {
    e.preventDefault();
    if (!disableCode && !disablePassword) return;
    disableLoading = true;
    twoFaMsg = "";
    try {
      const payload: { code?: string; password?: string } = {};
      if (disableCode) payload.code = disableCode;
      if (disablePassword) payload.password = disablePassword;
      await authApi.disable2fa(payload);
      if ($currentUser)
        currentUser.set({ ...$currentUser, totp_enabled: false });
      disablingTwoFa = false;
      disableCode = "";
      disablePassword = "";
      twoFaMsg = "2FA disabled";
      twoFaMsgType = "success";
    } catch (err) {
      twoFaMsg = (err as Error).message;
      twoFaMsgType = "error";
    } finally {
      disableLoading = false;
    }
  }

  function cancelDisable() {
    disablingTwoFa = false;
    disableCode = "";
    disablePassword = "";
  }

  function cancelSetup() {
    twoFaSetupActive = false;
    twoFaCode = "";
    twoFaMsg = "";
  }
</script>

<TopNav title={$t("settings.title")} />

<div class="main-content">
  {#if loading}
    <LoadingScreen icon="⚙" message={$t("settings.loading")} />
  {:else if error}
    <EmptyState
      icon="⚠️"
      title={$t("settings.load_error")}
      description={error}
    />
  {:else}
    <!-- Sync Status Section -->
    <div class="settings-section">
      <div class="settings-section-title">{$t("settings.sync_status")}</div>
      <div class="sync-status-bar" style="margin-bottom:var(--space-md)">
        <span
          class="sync-dot {syncRunning
            ? 'running'
            : syncHasError
              ? 'error'
              : 'idle'}"
        ></span>
        <div>
          <div>
            {syncRunning
              ? $t("settings.sync_running")
              : syncHasError
                ? $t("settings.sync_error")
                : $t("settings.sync_ready")}
          </div>
          <div style="font-size:0.75rem;color:var(--text-muted)">
            {$t("settings.last_sync", {
              values: {
                time: formatDateTimeLocale(syncStatus?.last_synced_at),
              },
            })}
            {#if nextSyncLabel && !syncRunning}
              <span style="color:var(--text-muted);opacity:0.7"
                >{$t("settings.next_sync", {
                  values: { label: nextSyncLabel },
                })}</span
              >
            {/if}
          </div>
          {#if syncHasError}
            <div style="font-size:0.75rem;color:var(--danger)">
              {syncStatus?.last_error ?? ""}
            </div>
          {/if}
        </div>
      </div>

      <button
        class="btn btn-secondary btn-full"
        disabled={regrouping}
        style="margin-top:var(--space-sm)"
        onclick={regroup}
      >
        {regrouping ? $t("settings.regrouping") : $t("settings.regroup")}
      </button>

      {#if !resetConfirmStep}
        <button
          class="btn btn-secondary btn-full"
          disabled={resetting}
          style="margin-top:var(--space-sm);border-color:var(--danger);color:var(--danger)"
          onclick={() => (resetConfirmStep = true)}
        >
          {resetting ? $t("settings.resetting") : $t("settings.reset")}
        </button>
      {:else}
        <div
          style="margin-top:var(--space-sm);padding:var(--space-md);border:1px solid var(--danger);border-radius:var(--radius-sm);background:color-mix(in srgb, var(--danger) 8%, transparent)"
        >
          <p
            style="margin:0 0 var(--space-sm);font-size:0.875rem;color:var(--danger);font-weight:600"
          >
            {$t("settings.reset_warning")}
          </p>
          <p
            style="margin:0 0 var(--space-sm);font-size:0.875rem;color:var(--text-secondary)"
          >
            {$t("settings.reset_type")}
          </p>
          <input
            class="form-input"
            type="text"
            bind:value={resetConfirmText}
            placeholder={$t("settings.reset_placeholder")}
            style="margin-bottom:var(--space-sm);font-family:monospace"
            onkeydown={(e) => {
              if (e.key === "Enter" && resetConfirmText === "RESET")
                resetAndSync();
              if (e.key === "Escape") cancelReset();
            }}
          />
          <div style="display:flex;gap:var(--space-sm)">
            <button
              class="btn btn-full"
              disabled={resetConfirmText !== "RESET" || resetting}
              style="background:var(--danger);color:#fff;border-color:var(--danger)"
              onclick={resetAndSync}
            >
              {resetting
                ? $t("settings.resetting")
                : $t("settings.reset_confirm")}
            </button>
            <button class="btn btn-secondary" onclick={cancelReset}
              >{$t("settings.cancel")}</button
            >
          </div>
        </div>
      {/if}
    </div>

    <!-- Email Account Section -->
    <div class="settings-section">
      <div class="settings-section-title">{$t("settings.email_account")}</div>

      <form onsubmit={saveSettings}>
        <div class="form-group">
          <label class="form-label" for="gmail-address"
            >{$t("settings.email_address")}</label
          >
          <input
            class="form-input"
            id="gmail-address"
            type="email"
            bind:value={gmailAddress}
            placeholder={$t("settings.email_placeholder")}
            autocomplete="email"
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="app-password"
            >{$t("settings.password")}</label
          >
          <input
            class="form-input"
            id="app-password"
            type="password"
            bind:value={appPassword}
            placeholder={currentSettings?.gmail_app_password_set
              ? $t("settings.password_set")
              : $t("settings.password_placeholder")}
            autocomplete="current-password"
          />
          <div class="form-hint">
            {$t("settings.password_hint")}
          </div>
        </div>

        <div class="form-group">
          <label class="form-label" for="imap-provider"
            >{$t("settings.imap_server")}</label
          >
          <select
            class="form-input"
            id="imap-provider"
            value={imapPreset}
            onchange={(e) =>
              applyImapPreset((e.target as HTMLSelectElement).value)}
            style="margin-bottom:var(--space-sm)"
          >
            {#each IMAP_PRESETS as p}
              <option value={p.label}>{p.label}</option>
            {/each}
            <option value="custom">Custom…</option>
          </select>
          <div style="display:flex;gap:var(--space-sm)">
            <input
              class="form-input"
              id="imap-host"
              type="text"
              bind:value={imapHost}
              placeholder={$t("settings.imap_host_placeholder")}
              style="flex:1"
            />
            <input
              class="form-input"
              id="imap-port"
              type="number"
              bind:value={imapPort}
              min="1"
              max="65535"
              style="width:90px"
            />
          </div>
          <button
            type="button"
            class="btn btn-secondary"
            style="margin-top:var(--space-sm);width:100%"
            disabled={testingImap}
            onclick={testImapConnection}
          >
            {testingImap
              ? $t("settings.testing")
              : $t("settings.test_connection")}
          </button>
          {#if imapTestMsg}
            <div
              style="margin-top:var(--space-xs);font-size:0.8rem;color:{imapTestOk
                ? 'var(--success)'
                : 'var(--danger)'}"
            >
              {imapTestMsg}
            </div>
          {/if}
        </div>

        {#if settingsMsg}
          <div
            style="min-height:24px;margin-bottom:var(--space-sm);color:{settingsMsgType ===
            'success'
              ? 'var(--success)'
              : settingsMsgType === 'error'
                ? 'var(--danger)'
                : 'var(--text-secondary)'}"
          >
            {settingsMsg}
          </div>
        {:else}
          <div style="min-height:24px;margin-bottom:var(--space-sm)"></div>
        {/if}

        <button
          class="btn btn-primary btn-full"
          type="submit"
          disabled={savingSettings}
        >
          {savingSettings ? $t("settings.saving") : $t("settings.save")}
        </button>
      </form>
    </div>

    <!-- Inbound SMTP Server (admin only — enable/port) -->
    {#if $currentUser?.is_admin}
      <div class="settings-section">
        <div class="settings-section-title">{$t("settings.inbound_smtp")}</div>
        <div
          style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)"
        >
          {$t("settings.smtp_desc")}
        </div>

        <form onsubmit={saveSettings}>
          <div class="form-group">
            <label
              class="form-label"
              style="display:flex;align-items:center;gap:var(--space-sm)"
            >
              <input
                type="checkbox"
                bind:checked={smtpEnabled}
                style="width:auto;margin:0"
              />
              {$t("settings.smtp_enable")}
            </label>
          </div>

          <div class="form-group">
            <label class="form-label" for="smtp-domain"
              >{$t("settings.smtp_domain")}</label
            >
            <input
              class="form-input"
              id="smtp-domain"
              type="text"
              bind:value={smtpDomain}
              placeholder={$t("settings.smtp_domain_placeholder")}
            />
            <div class="form-hint">{$t("settings.smtp_domain_hint")}</div>
          </div>

          <div class="form-group">
            <label class="form-label" for="sync-interval"
              >{$t("settings.sync_interval")}</label
            >
            <input
              class="form-input"
              id="sync-interval"
              type="number"
              bind:value={syncInterval}
              min="1"
              max="1440"
            />
            <div class="form-hint">{$t("settings.sync_interval_hint")}</div>
          </div>

          <div class="form-group">
            <label class="form-label" for="max-emails"
              >{$t("settings.max_emails")}</label
            >
            <input
              class="form-input"
              id="max-emails"
              type="number"
              bind:value={maxEmailsPerSync}
              min="1"
              max="10000"
            />
            <div class="form-hint">{$t("settings.max_emails_hint")}</div>
          </div>

          <div class="form-group">
            <label class="form-label" for="first-sync-days"
              >{$t("settings.first_sync_days")}</label
            >
            <input
              class="form-input"
              id="first-sync-days"
              type="number"
              bind:value={firstSyncDays}
              min="1"
              max="3650"
            />
            <div class="form-hint">{$t("settings.first_sync_days_hint")}</div>
          </div>

          {#if smtpEnabled}
            <div class="form-group">
              <label class="form-label" for="smtp-port"
                >{$t("settings.smtp_port")}</label
              >
              <input
                class="form-input"
                id="smtp-port"
                type="number"
                bind:value={smtpPort}
                min="1"
                max="65535"
                placeholder="2525"
              />
              <div class="form-hint">{$t("settings.smtp_port_hint")}</div>
            </div>
          {/if}

          {#if settingsMsg}
            <div
              style="min-height:24px;margin-bottom:var(--space-sm);color:{settingsMsgType ===
              'success'
                ? 'var(--success)'
                : settingsMsgType === 'error'
                  ? 'var(--danger)'
                  : 'var(--text-secondary)'}"
            >
              {settingsMsg}
            </div>
          {:else}
            <div style="min-height:24px;margin-bottom:var(--space-sm)"></div>
          {/if}

          <button
            class="btn btn-primary btn-full"
            type="submit"
            disabled={savingSettings}
          >
            {savingSettings ? $t("settings.saving") : $t("settings.save")}
          </button>
        </form>
      </div>
    {/if}

    <!-- Email Forwarding (per-user — shown when SMTP server is enabled) -->
    {#if smtpEnabled}
      <div class="settings-section">
        <div class="settings-section-title">
          {$t("settings.email_forwarding")}
        </div>
        <div
          style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)"
        >
          {$t("settings.forwarding_desc")}
        </div>

        <form onsubmit={saveSettings}>
          <div class="form-group">
            <label class="form-label" for="smtp-recipient"
              >{$t("settings.your_address")}</label
            >
            <input
              class="form-input"
              id="smtp-recipient"
              type="email"
              bind:value={smtpRecipient}
              placeholder={$t("settings.your_address_placeholder")}
            />
            <div class="form-hint">{$t("settings.your_address_hint")}</div>
          </div>

          <div class="form-group">
            <label class="form-label" for="smtp-senders"
              >{$t("settings.allowed_senders")}</label
            >
            <input
              class="form-input"
              id="smtp-senders"
              type="text"
              bind:value={smtpAllowedSenders}
              placeholder={$t("settings.allowed_senders_placeholder")}
            />
            <div class="form-hint">{$t("settings.allowed_senders_hint")}</div>
          </div>

          {#if settingsMsg}
            <div
              style="min-height:24px;margin-bottom:var(--space-sm);color:{settingsMsgType ===
              'success'
                ? 'var(--success)'
                : settingsMsgType === 'error'
                  ? 'var(--danger)'
                  : 'var(--text-secondary)'}"
            >
              {settingsMsg}
            </div>
          {:else}
            <div style="min-height:24px;margin-bottom:var(--space-sm)"></div>
          {/if}

          <button
            class="btn btn-primary btn-full"
            type="submit"
            disabled={savingSettings}
          >
            {savingSettings ? $t("settings.saving") : $t("settings.save")}
          </button>
        </form>
      </div>
    {/if}

    <!-- Airport Data Section -->
    <div class="settings-section">
      <div class="settings-section-title">{$t("settings.airports")}</div>
      <div
        style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)"
      >
        {#if airportCount > 0}
          {$t("settings.airports_loaded", {
            values: { n: airportCount.toLocaleString() },
          })}
        {:else}
          {$t("settings.airports_none")} Download <code>airports.csv</code> from
          <a href="https://ourairports.com/data/airports.csv" target="_blank"
            >ourairports.com</a
          >
          and place it in the <code>data/</code> directory.
        {/if}
      </div>
      {#if airportCount > 0}
        <button
          class="btn btn-secondary"
          disabled={reloadingAirports}
          onclick={reloadAirports}
        >
          {reloadingAirports
            ? $t("settings.reloading_airports")
            : $t("settings.reload_airports")}
        </button>
      {/if}
    </div>

    <!-- Admin: User Management -->
    {#if $currentUser?.is_admin}
      <div class="settings-section">
        <div class="settings-section-title">{$t("settings.admin")}</div>
        <a
          href="#/admin/users"
          class="btn btn-secondary btn-full"
          style="display:block;text-align:center;"
        >
          {$t("settings.manage_users")}
        </a>
      </div>
    {/if}

    <!-- Two-Factor Authentication -->
    <div class="settings-section">
      <div class="settings-section-title">{$t("settings.2fa")}</div>

      {#if twoFaMsg}
        <div
          style="font-size:0.875rem;margin-bottom:var(--space-sm);color:{twoFaMsgType ===
          'success'
            ? 'var(--success)'
            : 'var(--danger)'}"
        >
          {twoFaMsg}
        </div>
      {/if}

      {#if twoFaState === "enabled"}
        <div
          style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)"
        >
          {$t("settings.2fa_enabled_msg").replace("enabled", "")}
          <strong style="color:var(--success)"
            >{$t("settings.2fa_enabled_badge")}</strong
          >
          {" "}on your account.
        </div>
        {#if disablingTwoFa}
          <form onsubmit={confirmDisable2fa}>
            <div
              style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)"
            >
              {$t("settings.2fa_disable_hint")}
            </div>
            <div class="form-group">
              <label class="form-label" for="disable-totp-code"
                >{$t("settings.2fa_totp_code")}</label
              >
              <input
                class="form-input"
                id="disable-totp-code"
                type="text"
                inputmode="numeric"
                maxlength="6"
                placeholder={$t("settings.2fa_totp_placeholder")}
                bind:value={disableCode}
                autocomplete="one-time-code"
              />
            </div>
            <div
              style="text-align:center;font-size:0.8rem;color:var(--text-muted);margin-bottom:var(--space-sm)"
            >
              {$t("settings.2fa_or")}
            </div>
            <div class="form-group">
              <label class="form-label" for="disable-pw"
                >{$t("settings.2fa_current_pw")}</label
              >
              <input
                class="form-input"
                id="disable-pw"
                type="password"
                bind:value={disablePassword}
                placeholder={$t("settings.2fa_current_pw_placeholder")}
                autocomplete="current-password"
              />
            </div>
            <div style="display:flex;gap:var(--space-sm)">
              <button
                class="btn btn-secondary"
                type="button"
                onclick={cancelDisable}
                disabled={disableLoading}
              >
                {$t("settings.cancel")}
              </button>
              <button
                class="btn btn-primary"
                type="submit"
                style="flex:1;border-color:var(--danger);background:var(--danger)"
                disabled={disableLoading || (!disableCode && !disablePassword)}
              >
                {disableLoading
                  ? $t("settings.2fa_disabling")
                  : $t("settings.2fa_disable")}
              </button>
            </div>
          </form>
        {:else}
          <button
            class="btn btn-secondary btn-full"
            style="border-color:var(--danger);color:var(--danger)"
            onclick={() => {
              disablingTwoFa = true;
              twoFaMsg = "";
            }}
          >
            {$t("settings.2fa_disable")}
          </button>
        {/if}
      {:else if twoFaState === "setup"}
        <div
          style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)"
        >
          {$t("settings.2fa_setup_hint")}
        </div>
        {#if twoFaQrSvg}
          <div style="text-align:center;margin-bottom:var(--space-md)">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            <div
              style="display:inline-block;width:260px;height:260px;padding:12px;background:#fff;border-radius:var(--radius-sm);border:1px solid var(--border)"
            >
              {@html twoFaQrSvg}
            </div>
          </div>
        {/if}
        <div
          style="font-size:0.8rem;color:var(--text-muted);margin-bottom:var(--space-md);word-break:break-all"
        >
          {$t("settings.2fa_manual_key")}
          <code style="font-size:0.85rem">{twoFaSecret}</code>
        </div>
        <form onsubmit={confirmEnable2fa}>
          <div class="form-group">
            <label class="form-label" for="enable-totp-code"
              >{$t("settings.2fa_code_label")}</label
            >
            <input
              class="form-input"
              id="enable-totp-code"
              type="text"
              inputmode="numeric"
              maxlength="6"
              placeholder="000000"
              bind:value={twoFaCode}
              autocomplete="one-time-code"
              autofocus
            />
          </div>
          <div style="display:flex;gap:var(--space-sm)">
            <button
              class="btn btn-secondary"
              type="button"
              onclick={cancelSetup}
              disabled={twoFaLoading}
            >
              {$t("settings.cancel")}
            </button>
            <button
              class="btn btn-primary"
              type="submit"
              style="flex:1"
              disabled={twoFaLoading || twoFaCode.length !== 6}
            >
              {twoFaLoading
                ? $t("settings.2fa_enabling")
                : $t("settings.2fa_enable")}
            </button>
          </div>
        </form>
      {:else}
        <div
          style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)"
        >
          {$t("settings.2fa_idle_hint")}
        </div>
        <button
          class="btn btn-primary btn-full"
          disabled={twoFaLoading}
          onclick={startSetup2fa}
        >
          {twoFaLoading
            ? $t("settings.2fa_loading")
            : $t("settings.2fa_idle_btn")}
        </button>
      {/if}
    </div>

    <!-- Appearance -->
    <div class="settings-section">
      <div class="settings-section-title">{$t("settings.appearance")}</div>
      <div class="theme-toggle">
        {#each [["system", $t("settings.theme_system")], ["light", $t("settings.theme_light")], ["dark", $t("settings.theme_dark")]] as [value, label]}
          <button
            class="theme-btn"
            class:active={$theme === value}
            onclick={() => theme.set(value as "system" | "light" | "dark")}
            >{label}</button
          >
        {/each}
      </div>
      <div class="form-group" style="margin-top:var(--space-md)">
        <label class="form-label" for="language-select"
          >{$t("settings.language")}</label
        >
        <select
          id="language-select"
          class="form-input"
          value={$locale}
          onchange={(e) => setLocale((e.target as HTMLSelectElement).value)}
        >
          {#each LOCALES as loc}
            <option value={loc.value}>{loc.label}</option>
          {/each}
        </select>
      </div>
    </div>

    <!-- Change Password -->
    <div class="settings-section">
      <div class="settings-section-title">{$t("settings.change_password")}</div>
      <form onsubmit={changePassword}>
        <div class="form-group">
          <label class="form-label" for="cur-pw"
            >{$t("settings.current_pw")}</label
          >
          <input
            class="form-input"
            id="cur-pw"
            type="password"
            bind:value={currentPw}
            placeholder={$t("settings.current_pw_placeholder")}
            autocomplete="current-password"
          />
        </div>
        <div class="form-group">
          <label class="form-label" for="new-pw">{$t("settings.new_pw")}</label>
          <input
            class="form-input"
            id="new-pw"
            type="password"
            bind:value={newPw}
            placeholder={$t("settings.new_pw_placeholder")}
            autocomplete="new-password"
          />
        </div>
        {#if $currentUser?.totp_enabled}
          <div class="form-group">
            <label class="form-label" for="pw-totp"
              >{$t("settings.pw_totp")}</label
            >
            <input
              class="form-input"
              id="pw-totp"
              type="text"
              inputmode="numeric"
              maxlength="6"
              bind:value={pwTotpCode}
              placeholder={$t("settings.pw_totp_placeholder")}
              autocomplete="one-time-code"
            />
          </div>
        {/if}
        {#if pwMsg}
          <div
            style="font-size:0.875rem;margin-bottom:var(--space-sm);color:{pwMsgType ===
            'success'
              ? 'var(--success)'
              : 'var(--danger)'}"
          >
            {pwMsg}
          </div>
        {/if}
        <button
          class="btn btn-primary btn-full"
          type="submit"
          disabled={changingPw}
        >
          {changingPw
            ? $t("settings.changing_pw")
            : $t("settings.change_pw_btn")}
        </button>
      </form>
    </div>
  {/if}
</div>

<style>
  .theme-toggle {
    display: flex;
    gap: var(--space-xs);
    background: var(--bg-primary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 3px;
  }

  .theme-btn {
    flex: 1;
    padding: 6px 0;
    border: none;
    border-radius: calc(var(--radius-sm) - 2px);
    background: transparent;
    color: var(--text-secondary);
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition:
      background 0.15s,
      color 0.15s;
  }

  .theme-btn.active {
    background: var(--accent);
    color: #fff;
  }
</style>
