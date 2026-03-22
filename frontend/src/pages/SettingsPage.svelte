<script lang="ts">
  import { onDestroy } from "svelte";
  import QRCode from "qrcode";
  import { settingsApi, syncApi, authApi, notificationsApi, failedEmailsApi } from "../api/client";
  import type { Settings, SyncStatus, NotifPreferences, FailedEmail, AdminFailedEmailGroup } from "../api/types";
  import LoadingScreen from "../components/LoadingScreen.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import TopNav from "../components/TopNav.svelte";
  import SyncStatusBar from "../components/SyncStatusBar.svelte";
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

  // Immich
  let immichUrl = $state("");
  let immichApiKey = $state("");
  let savingImmich = $state(false);
  let immichMsg = $state("");
  let immichMsgType = $state<"success" | "error">("success");
  let testingImmich = $state(false);

  // Notifications — admin VAPID config status
  let vapidConfigured = $state(false);
  let vapidSource = $state("");

  async function loadVapidStatus() {
    try {
      const s = await notificationsApi.vapidStatus();
      vapidConfigured = s.configured;
      vapidSource = s.source;
    } catch { /* non-admin — ignore */ }
  }

  if ($currentUser?.is_admin) loadVapidStatus();

  // Notifications — per-user
  let notifStatus = $state<"unsupported" | "denied" | "default" | "subscribed" | "unsubscribed">("default");
  let notifPrefs = $state<NotifPreferences>({ flight_reminder: true, checkin_reminder: true, trip_reminder: true, delay_alert: true, boarding_pass: true });
  let savingNotifPrefs = $state(false);
  let togglingNotif = $state(false);
  let testingPush = $state(false);
  let notifMsg = $state("");
  let notifMsgType = $state<"success" | "error">("success");

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
      immichUrl = s.immich_url ?? "";
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

  // ---- Notifications ----
  async function loadNotifStatus() {
    const { getStatus, isSupported } = await import("../lib/notifications");
    if (!isSupported()) {
      notifStatus = "unsupported";
      return;
    }
    notifStatus = await getStatus();
    if (notifStatus === "subscribed" || notifStatus === "unsubscribed") {
      try {
        notifPrefs = await notificationsApi.getPreferences();
      } catch { /* ignore */ }
    }
  }

  loadNotifStatus();

  async function togglePushSubscription() {
    togglingNotif = true;
    notifMsg = "";
    try {
      if (notifStatus === "subscribed") {
        const { unsubscribe } = await import("../lib/notifications");
        await unsubscribe();
        notifMsg = $t("settings.notif_disabled_ok");
        notifMsgType = "success";
      } else {
        // Check server is ready before requesting browser permission
        try {
          await notificationsApi.vapidPublicKey();
        } catch {
          notifMsg = $t("settings.notif_not_configured") + ($currentUser?.is_admin ? $t("settings.notif_not_configured_admin") : $t("settings.notif_not_configured_user"));
          notifMsgType = "error";
          return;
        }
        const { subscribe } = await import("../lib/notifications");
        const ok = await subscribe();
        if (ok) {
          notifMsg = $t("settings.notif_enabled_ok");
          notifMsgType = "success";
        } else {
          notifMsg = $t("settings.notif_permission_error");
          notifMsgType = "error";
        }
      }
      const { getStatus } = await import("../lib/notifications");
      notifStatus = await getStatus();
      if (notifStatus === "subscribed") {
        notifPrefs = await notificationsApi.getPreferences();
      }
    } catch (err) {
      notifMsg = (err as Error).message;
      notifMsgType = "error";
    } finally {
      togglingNotif = false;
    }
  }

  async function saveNotifPrefs(e: Event) {
    e.preventDefault();
    savingNotifPrefs = true;
    notifMsg = "";
    try {
      await notificationsApi.updatePreferences(notifPrefs);
      notifMsg = $t("settings.notif_prefs_saved");
      notifMsgType = "success";
    } catch (err) {
      notifMsg = (err as Error).message;
      notifMsgType = "error";
    } finally {
      savingNotifPrefs = false;
    }
  }

  async function sendTestPush() {
    testingPush = true;
    notifMsg = "";
    try {
      const result = await notificationsApi.testPush();
      notifMsg = result.ok ? $t("settings.notif_test_ok") : $t("settings.notif_test_none");
      notifMsgType = result.ok ? "success" : "error";
    } catch (err) {
      notifMsg = (err as Error).message;
      notifMsgType = "error";
    } finally {
      testingPush = false;
    }
  }

  // ---- Immich settings ----
  async function saveImmich(e: Event) {
    e.preventDefault();
    savingImmich = true;
    immichMsg = "";
    try {
      const data: Record<string, string> = { immich_url: immichUrl.trim() };
      if (immichApiKey) data.immich_api_key = immichApiKey;
      await settingsApi.update(data);
      immichMsg = "Immich settings saved";
      immichMsgType = "success";
      immichApiKey = "";
      if (currentSettings) currentSettings = { ...currentSettings, immich_url: immichUrl.trim(), immich_api_key_set: currentSettings.immich_api_key_set || !!immichApiKey };
    } catch (err) {
      immichMsg = (err as Error).message;
      immichMsgType = "error";
    } finally {
      savingImmich = false;
    }
  }

  async function testImmichConnection() {
    testingImmich = true;
    immichMsg = "";
    // Save first so the server has the latest values
    if (immichUrl.trim() || immichApiKey) {
      try {
        const data: Record<string, string> = { immich_url: immichUrl.trim() };
        if (immichApiKey) data.immich_api_key = immichApiKey;
        await settingsApi.update(data);
        immichApiKey = "";
      } catch { /* ignore save error, test will still fail with a clear message */ }
    }
    try {
      const result = await settingsApi.testImmich();
      immichMsg = result.message;
      immichMsgType = "success";
    } catch (err) {
      immichMsg = (err as Error).message;
      immichMsgType = "error";
    } finally {
      testingImmich = false;
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

  // ---- 2FA state ----
  // 'idle' | 'setup' | 'enabled' | 'disabling'
  let twoFaState = $derived.by(() => {
    if ($currentUser?.totp_enabled) return "enabled" as const;
    return twoFaSetupActive ? ("setup" as const) : ("idle" as const);
  });

  let twoFaSetupActive = $state(false);
  let twoFaSecret = $state("");
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

  // ---- Failed emails ----
  let failedEmails = $state<FailedEmail[]>([]);
  let failedEmailsLoading = $state(false);
  let retryingEmailId = $state<string | null>(null);
  let failedEmailMsg = $state<Record<string, { text: string; ok: boolean }>>({});

  let adminFailedGroups = $state<AdminFailedEmailGroup[]>([]);
  let adminRetryingAll = $state(false);

  async function loadFailedEmails() {
    failedEmailsLoading = true;
    try {
      failedEmails = await failedEmailsApi.list();
      if ($currentUser?.is_admin) {
        adminFailedGroups = await failedEmailsApi.adminList().catch(() => []);
      }
    } catch { /* ignore */ } finally {
      failedEmailsLoading = false;
    }
  }

  loadFailedEmails();

  async function retryFailedEmail(id: string) {
    retryingEmailId = id;
    failedEmailMsg = { ...failedEmailMsg, [id]: { text: '', ok: false } };
    try {
      const result = await failedEmailsApi.retry(id);
      if (result.status === 'recovered') {
        failedEmails = failedEmails.filter(e => e.id !== id);
        failedEmailMsg = { ...failedEmailMsg, [id]: { text: $t('settings.failed_email_recovered'), ok: true } };
      } else {
        const updated = result.record;
        if (updated) failedEmails = failedEmails.map(e => e.id === id ? updated : e);
        failedEmailMsg = { ...failedEmailMsg, [id]: { text: $t('settings.failed_email_still_failing'), ok: false } };
      }
    } catch (err) {
      failedEmailMsg = { ...failedEmailMsg, [id]: { text: (err as Error).message, ok: false } };
    } finally {
      retryingEmailId = null;
    }
  }

  async function dismissFailedEmail(id: string) {
    try {
      await failedEmailsApi.delete(id);
      failedEmails = failedEmails.filter(e => e.id !== id);
    } catch { /* ignore */ }
  }

  async function adminDeleteSender(sender: string) {
    try {
      await failedEmailsApi.adminDeleteSender(sender);
      adminFailedGroups = adminFailedGroups.filter(g => g.sender_domain !== sender);
      failedEmails = failedEmails.filter(e => e.airline_hint !== sender);
    } catch { /* ignore */ }
  }

  async function adminRetryAll() {
    adminRetryingAll = true;
    try {
      await failedEmailsApi.adminRetryAll();
      await loadFailedEmails();
    } catch { /* ignore */ } finally {
      adminRetryingAll = false;
    }
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
      <SyncStatusBar {syncStatus} style="margin-bottom:var(--space-md)" />

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

        {#if $currentUser?.is_admin}
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

    <!-- Admin: Push Notifications status (keys are auto-generated on startup) -->
    {#if $currentUser?.is_admin}
      <div class="settings-section">
        <div class="settings-section-title">{$t("settings.push_title")}</div>
        <div style="display:flex;align-items:center;gap:var(--space-sm);font-size:0.875rem">
          <span style="width:10px;height:10px;flex-shrink:0;border-radius:50%;background:{vapidConfigured ? 'var(--success)' : 'var(--warning, #f59e0b)'}"></span>
          {#if vapidConfigured}
            {$t("settings.push_ready", { values: { source: vapidSource === "env" ? $t("settings.push_source_env") : $t("settings.push_source_auto") } })}
          {:else}
            {$t("settings.push_not_ready")}
          {/if}
        </div>
      </div>
    {/if}

    <!-- Push Notifications Section -->
    <div class="settings-section">
      <div class="settings-section-title">{$t("settings.notif_title")}</div>
      {#if notifStatus === "unsupported"}
        <p style="font-size:0.875rem;color:var(--text-secondary)">
          {$t("settings.notif_unsupported")}
        </p>
      {:else if notifStatus === "denied"}
        <p style="font-size:0.875rem;color:var(--danger)">
          {$t("settings.notif_denied")}
        </p>
      {:else}
        <p style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)">
          {$t("settings.notif_desc")}
        </p>

        <button
          class="btn {notifStatus === 'subscribed' ? 'btn-secondary' : 'btn-primary'} btn-full"
          disabled={togglingNotif}
          onclick={togglePushSubscription}
          style={notifStatus === "subscribed" ? "border-color:var(--danger);color:var(--danger)" : ""}
        >
          {togglingNotif
            ? $t("settings.notif_toggling")
            : notifStatus === "subscribed"
              ? $t("settings.notif_disable")
              : $t("settings.notif_enable")}
        </button>

        {#if notifStatus === "subscribed"}
          <form onsubmit={saveNotifPrefs} style="margin-top:var(--space-md)">
            <div class="settings-section-title" style="font-size:0.875rem;margin-bottom:var(--space-sm)">{$t("settings.notif_what")}</div>
            <label style="display:flex;align-items:center;gap:var(--space-sm);font-size:0.875rem;margin-bottom:var(--space-sm);cursor:pointer">
              <input type="checkbox" bind:checked={notifPrefs.flight_reminder} style="width:auto;margin:0" />
              {$t("settings.notif_flight_reminder")}
            </label>
            <label style="display:flex;align-items:center;gap:var(--space-sm);font-size:0.875rem;margin-bottom:var(--space-sm);cursor:pointer">
              <input type="checkbox" bind:checked={notifPrefs.checkin_reminder} style="width:auto;margin:0" />
              {$t("settings.notif_checkin_reminder")}
            </label>
            <label style="display:flex;align-items:center;gap:var(--space-sm);font-size:0.875rem;margin-bottom:var(--space-sm);cursor:pointer">
              <input type="checkbox" bind:checked={notifPrefs.trip_reminder} style="width:auto;margin:0" />
              {$t("settings.notif_trip_reminder")}
            </label>
            <label style="display:flex;align-items:center;gap:var(--space-sm);font-size:0.875rem;margin-bottom:var(--space-sm);cursor:pointer">
              <input type="checkbox" bind:checked={notifPrefs.delay_alert} style="width:auto;margin:0" />
              {$t("settings.notif_delay_alert")}
            </label>
            <label style="display:flex;align-items:center;gap:var(--space-sm);font-size:0.875rem;margin-bottom:var(--space-md);cursor:pointer">
              <input type="checkbox" bind:checked={notifPrefs.boarding_pass} style="width:auto;margin:0" />
              {$t("settings.notif_boarding_pass")}
            </label>
            <div style="display:flex;gap:var(--space-sm)">
              <button class="btn btn-primary btn-full" type="submit" disabled={savingNotifPrefs}>
                {savingNotifPrefs ? $t("settings.notif_saving") : $t("settings.notif_save")}
              </button>
              <button class="btn btn-secondary" type="button" disabled={testingPush} onclick={sendTestPush}>
                {testingPush ? $t("settings.notif_testing") : $t("settings.notif_test")}
              </button>
            </div>
          </form>
        {/if}

        {#if notifMsg}
          <p style="font-size:0.875rem;margin-top:var(--space-sm);color:{notifMsgType === 'success' ? 'var(--success)' : 'var(--danger)'}">
            {notifMsg}
          </p>
        {/if}
      {/if}
    </div>

    <!-- Immich Integration Section -->
    <div class="settings-section">
      <div class="settings-section-title">Immich</div>
      <p style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)">
        Connect your self-hosted <a href="https://immich.app" target="_blank" rel="noopener" style="color:var(--accent)">Immich</a> instance to create photo albums from completed trips.
      </p>
      <form onsubmit={saveImmich}>
        <div class="form-group">
          <label class="form-label" for="immich-url">Immich URL</label>
          <input
            class="form-input"
            id="immich-url"
            type="url"
            bind:value={immichUrl}
            placeholder="https://immich.example.com"
            autocomplete="off"
          />
        </div>
        <div class="form-group">
          <label class="form-label" for="immich-api-key">API Key</label>
          <input
            class="form-input"
            id="immich-api-key"
            type="password"
            bind:value={immichApiKey}
            placeholder={currentSettings?.immich_api_key_set ? "••••••••  (set — enter new key to change)" : "Paste your Immich API key"}
            autocomplete="off"
          />
        </div>
        {#if immichMsg}
          <p style="font-size:0.875rem;margin-bottom:var(--space-sm);color:{immichMsgType === 'success' ? 'var(--success)' : 'var(--danger)'}">
            {immichMsg}
          </p>
        {/if}
        <div style="display:flex;gap:var(--space-sm)">
          <button class="btn btn-primary btn-full" type="submit" disabled={savingImmich}>
            {savingImmich ? "Saving…" : "Save Immich Settings"}
          </button>
          <button
            class="btn btn-secondary"
            type="button"
            disabled={testingImmich}
            onclick={testImmichConnection}
          >
            {testingImmich ? "…" : "Test"}
          </button>
        </div>
      </form>
    </div>

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

    <!-- Failed emails: user view -->
    <div class="settings-section">
      <div class="settings-section-title">{$t("settings.failed_emails")}</div>
      <p style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)">
        {$t("settings.failed_emails_desc")}
      </p>
      {#if failedEmailsLoading}
        <p style="font-size:0.875rem;color:var(--text-secondary)">{$t("settings.failed_emails_loading")}</p>
      {:else if failedEmails.length === 0}
        <p style="font-size:0.875rem;color:var(--success)">{$t("settings.failed_emails_none")}</p>
      {:else}
        {#each failedEmails as fe (fe.id)}
          <div style="padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);margin-bottom:8px">
            <div style="font-size:0.875rem;font-weight:600;margin-bottom:2px">{fe.subject || '(no subject)'}</div>
            <div style="font-size:0.8rem;color:var(--text-secondary)">
              {$t("settings.failed_email_hint", { values: { sender: fe.sender } })}
              {#if fe.received_at} · {new Date(fe.received_at).toLocaleDateString()}{/if}
            </div>
            <div style="font-size:0.8rem;color:var(--danger);margin-top:2px">
              {$t("settings.failed_email_reason", { values: { reason: fe.reason } })}
            </div>
            {#if failedEmailMsg[fe.id]}
              <div style="font-size:0.8rem;margin-top:4px;color:{failedEmailMsg[fe.id].ok ? 'var(--success)' : 'var(--danger)'}">
                {failedEmailMsg[fe.id].text}
              </div>
            {/if}
            <div style="display:flex;gap:8px;margin-top:8px">
              <button
                class="btn btn-secondary"
                style="font-size:0.8rem;padding:4px 10px"
                disabled={retryingEmailId === fe.id}
                onclick={() => retryFailedEmail(fe.id)}
              >
                {retryingEmailId === fe.id ? $t("settings.failed_email_retrying") : $t("settings.failed_email_retry")}
              </button>
              <button
                class="btn btn-secondary"
                style="font-size:0.8rem;padding:4px 10px"
                onclick={() => dismissFailedEmail(fe.id)}
              >
                {$t("settings.failed_email_dismiss")}
              </button>
            </div>
          </div>
        {/each}
      {/if}
    </div>

    <!-- Admin: parse failures grouped by sender -->
    {#if $currentUser?.is_admin}
      <div class="settings-section">
        <div class="settings-section-title">{$t("settings.admin_failed_emails")}</div>
        <p style="font-size:0.875rem;color:var(--text-secondary);margin-bottom:var(--space-md)">
          {$t("settings.admin_failed_emails_desc")}
        </p>
        {#if adminFailedGroups.length === 0}
          <p style="font-size:0.875rem;color:var(--success)">{$t("settings.admin_failed_emails_none")}</p>
        {:else}
          {#each adminFailedGroups as grp (grp.sender_domain)}
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)">
              <span style="font-size:0.875rem">
                {$t("settings.admin_failed_emails_sender", { values: { sender: grp.sender_domain || '(unknown)', count: grp.count } })}
              </span>
              <button
                class="btn btn-secondary"
                style="font-size:0.8rem;padding:3px 10px"
                onclick={() => adminDeleteSender(grp.sender_domain)}
              >
                {$t("settings.admin_failed_emails_delete")}
              </button>
            </div>
          {/each}
          <button
            class="btn btn-secondary btn-full"
            style="margin-top:var(--space-sm)"
            disabled={adminRetryingAll}
            onclick={adminRetryAll}
          >
            {adminRetryingAll ? $t("settings.admin_failed_emails_retrying") : $t("settings.admin_failed_emails_retry_all")}
          </button>
        {/if}
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
            <!-- svelte-ignore a11y_autofocus -->
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
