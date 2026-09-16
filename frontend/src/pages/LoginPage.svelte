<script lang="ts">
  import { onMount } from 'svelte';
  import { authApi } from '../api/client';
  import { currentUser } from '../lib/authStore';
  import { refreshInvitationCount } from '../lib/invitationStore';
  import { t, applyUserLocale } from '../lib/i18n';
  import { applyUserAccent } from '../lib/accentStore';
  import { purgeApiCache } from '../lib/apiCache';
  import type { PublicConfig, User } from '../api/types';

  // Only a deliberately-configured demo instance answers with credentials here;
  // every other install returns `demo: false` and this block never renders.
  let demo = $state<PublicConfig | null>(null);

  onMount(async () => {
    try {
      const config = await authApi.publicConfig();
      if (config?.demo) demo = config;
    } catch {
      // An install too old to know this endpoint, or offline: the login form
      // is the feature, the demo notice is decoration. Never block on it.
    }
  });

  let username = $state('');
  let password = $state('');
  let loading = $state(false);
  let error = $state<string | null>(null);

  // 2FA step state
  let step = $state<'credentials' | 'totp'>('credentials');
  let totpCode = $state('');
  let totpLoading = $state(false);
  let totpError = $state<string | null>(null);

  // TOTP countdown
  let secondsLeft = $state(30 - (Math.floor(Date.now() / 1000) % 30));
  let countdownInterval: ReturnType<typeof setInterval> | null = null;

  function startCountdown() {
    if (countdownInterval) clearInterval(countdownInterval);
    countdownInterval = setInterval(() => {
      secondsLeft = 30 - (Math.floor(Date.now() / 1000) % 30);
    }, 1000);
  }

  function stopCountdown() {
    if (countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = null;
    }
  }

  async function handleLogin(e: Event) {
    e.preventDefault();
    await doLogin();
  }

  /** Fills the form in full view rather than posting the credentials behind the
   * visitor's back — they are printed above, and this is the same sign-in. */
  async function signInAsDemo() {
    if (!demo || loading) return;
    username = demo.demo_username;
    password = demo.demo_password;
    await doLogin();
  }

  async function doLogin() {
    if (!username.trim() || !password) return;

    loading = true;
    error = null;
    try {
      const result = await authApi.login({ username: username.trim(), password });
      if (result.requires_2fa) {
        step = 'totp';
        totpCode = '';
        totpError = null;
        secondsLeft = 30 - (Math.floor(Date.now() / 1000) % 30);
        startCountdown();
      } else {
        const user = result as User;
        currentUser.set(user);
        applyUserLocale(user.locale);
        // Adopted here as well as in App.svelte's boot check: signing in does
        // not remount the app, so without this the next person on a shared
        // browser keeps the previous one's colour until a reload.
        applyUserAccent(user.accent);
        // Whoever used this install last must not leak into this session.
        await purgeApiCache();
        refreshInvitationCount();
        window.location.hash = '/trips';
      }
    } catch (err) {
      error = (err as Error).message || 'Login failed';
    } finally {
      loading = false;
    }
  }

  async function handleTotpInput(e: Event) {
    const input = e.target as HTMLInputElement;
    // Allow only digits
    totpCode = input.value.replace(/\D/g, '').slice(0, 6);
    input.value = totpCode;
    if (totpCode.length === 6) {
      await submitTotp();
    }
  }

  async function submitTotp(e?: Event) {
    e?.preventDefault();
    if (totpCode.length !== 6 || totpLoading) return;

    totpLoading = true;
    totpError = null;
    try {
      const user = await authApi.verify2fa(totpCode);
      stopCountdown();
      currentUser.set(user);
      applyUserLocale(user.locale);
      applyUserAccent(user.accent);
      // The 2FA path signs in just as completely as the password-only one, so
      // it has to drop the previous account's cache too.
      await purgeApiCache();
      refreshInvitationCount();
      window.location.hash = '/trips';
    } catch (err) {
      totpError = (err as Error).message || 'Invalid code';
      totpCode = '';
    } finally {
      totpLoading = false;
    }
  }

  function backToCredentials() {
    stopCountdown();
    step = 'credentials';
    totpCode = '';
    totpError = null;
    password = '';
  }
</script>

<div class="auth-page">
  <div class="auth-card">
    <div class="auth-logo">✈</div>
    <h1 class="auth-title">{$t('login.title')}</h1>

    {#if step === 'credentials'}
      <p class="auth-subtitle">{$t('login.subtitle')}</p>

      {#if demo}
        <div class="demo-note">
          <p class="demo-note-title">{$t('login.demo_title')}</p>
          <p class="demo-note-hint">{$t('login.demo_hint')}</p>
          <dl class="demo-creds">
            <dt>{$t('login.username')}</dt>
            <dd>{demo.demo_username}</dd>
            <dt>{$t('login.password')}</dt>
            <dd>{demo.demo_password}</dd>
          </dl>
          <button
            class="btn btn-secondary btn-full demo-btn"
            type="button"
            onclick={signInAsDemo}
            disabled={loading}
          >
            {$t('login.demo_signin')}
          </button>
        </div>
      {/if}

      <form onsubmit={handleLogin}>
        <div class="form-group">
          <label class="form-label" for="login-username">{$t('login.username')}</label>
          <input
            class="form-input"
            id="login-username"
            type="text"
            bind:value={username}
            placeholder={$t('login.username_placeholder')}
            autocomplete="username"
            required
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="login-password">{$t('login.password')}</label>
          <input
            class="form-input"
            id="login-password"
            type="password"
            bind:value={password}
            placeholder={$t('login.password_placeholder')}
            autocomplete="current-password"
            required
          />
        </div>

        {#if error}
          <div class="auth-error">{error}</div>
        {/if}

        <button class="btn btn-primary btn-full" type="submit" disabled={loading}>
          {loading ? $t('login.submitting') : $t('login.submit')}
        </button>
      </form>

    {:else}
      <p class="auth-subtitle">{$t('totp.title')}</p>
      <p class="totp-hint">
        {$t('totp.hint')}
        <span class="totp-timer">{$t('totp.expires', { values: { s: secondsLeft } })}</span>
      </p>

      <form onsubmit={submitTotp}>
        <div class="form-group">
          <label class="form-label" for="totp-code">{$t('totp.code_label')}</label>
          <!-- svelte-ignore a11y_autofocus -->
          <input
            class="form-input totp-input"
            id="totp-code"
            type="text"
            inputmode="numeric"
            pattern="[0-9]*"
            maxlength="6"
            placeholder={$t('totp.code_placeholder')}
            autocomplete="one-time-code"
            value={totpCode}
            oninput={handleTotpInput}
            disabled={totpLoading}
            autofocus
          />
        </div>

        {#if totpError}
          <div class="auth-error">{totpError}</div>
        {/if}

        <button class="btn btn-primary btn-full" type="submit" disabled={totpLoading || totpCode.length !== 6}>
          {totpLoading ? $t('totp.submitting') : $t('totp.submit')}
        </button>
      </form>

      <button class="btn-back" onclick={backToCredentials}>
        {$t('totp.back')}
      </button>
    {/if}
  </div>
</div>

<style>
  .auth-page {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: var(--space-lg);
    background: var(--bg-primary);
  }

  .auth-card {
    width: 100%;
    max-width: 360px;
    background: var(--bg-secondary);
    border-radius: var(--radius-lg);
    padding: var(--space-xl);
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
  }

  .auth-logo {
    font-size: 2.5rem;
    text-align: center;
    margin-bottom: var(--space-sm);
  }

  .auth-title {
    font-size: 1.5rem;
    font-weight: 700;
    text-align: center;
    margin: 0 0 var(--space-xs);
  }

  .auth-subtitle {
    text-align: center;
    color: var(--text-secondary);
    font-size: 0.875rem;
    margin: 0 0 var(--space-xl);
  }

  /* Neutral panel on purpose: the accent is worn by the sign-in button, and a
     notice is not a status. */
  .demo-note {
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    background: var(--bg-subtle);
    padding: var(--space-md);
    margin-bottom: var(--space-lg);
  }

  .demo-note-title {
    margin: 0 0 var(--space-xs);
    font-size: 0.875rem;
    font-weight: 600;
  }

  .demo-note-hint {
    margin: 0 0 var(--space-sm);
    font-size: 0.8rem;
    color: var(--text-secondary);
  }

  .demo-creds {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 2px var(--space-sm);
    margin: 0 0 var(--space-md);
    font-size: 0.875rem;
  }

  .demo-creds dt {
    color: var(--text-secondary);
  }

  .demo-creds dd {
    margin: 0;
    font-family: var(--font-mono);
    /* A password read off a screen and typed elsewhere has to be selectable. */
    user-select: all;
    word-break: break-all;
  }

  .demo-btn {
    margin: 0;
  }

  .auth-error {
    color: var(--danger);
    font-size: 0.875rem;
    margin-bottom: var(--space-md);
    padding: var(--space-sm);
    background: color-mix(in srgb, var(--danger) 12%, transparent);
    border-radius: var(--radius-sm);
  }

  .totp-hint {
    font-size: 0.875rem;
    color: var(--text-secondary);
    margin: 0 0 var(--space-lg);
    text-align: center;
  }

  .totp-timer {
    display: block;
    margin-top: var(--space-xs);
    font-size: 0.8rem;
    color: var(--text-muted);
  }

  .totp-input {
    text-align: center;
    font-size: 1.5rem;
    letter-spacing: 0.5em;
    font-variant-numeric: tabular-nums;
  }

  .btn-back {
    display: block;
    width: 100%;
    margin-top: var(--space-md);
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 0.875rem;
    cursor: pointer;
    text-align: center;
    padding: var(--space-sm);
  }

  .btn-back:hover {
    color: var(--text-primary);
  }
</style>
