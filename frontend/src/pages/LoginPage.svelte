<script lang="ts">
  import { authApi } from '../api/client';
  import { currentUser } from '../lib/authStore';
  import type { User } from '../api/types';

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
        currentUser.set(result as User);
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
    <h1 class="auth-title">Partiu</h1>

    {#if step === 'credentials'}
      <p class="auth-subtitle">Sign in to your account</p>

      <form onsubmit={handleLogin}>
        <div class="form-group">
          <label class="form-label" for="login-username">Username</label>
          <input
            class="form-input"
            id="login-username"
            type="text"
            bind:value={username}
            placeholder="username"
            autocomplete="username"
            required
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="login-password">Password</label>
          <input
            class="form-input"
            id="login-password"
            type="password"
            bind:value={password}
            placeholder="••••••"
            autocomplete="current-password"
            required
          />
        </div>

        {#if error}
          <div class="auth-error">{error}</div>
        {/if}

        <button class="btn btn-primary btn-full" type="submit" disabled={loading}>
          {loading ? 'Signing in...' : 'Sign In'}
        </button>
      </form>

    {:else}
      <p class="auth-subtitle">Two-factor authentication</p>
      <p class="totp-hint">
        Enter the 6-digit code from your authenticator app.
        <span class="totp-timer">Code expires in {secondsLeft}s</span>
      </p>

      <form onsubmit={submitTotp}>
        <div class="form-group">
          <label class="form-label" for="totp-code">Authenticator Code</label>
          <input
            class="form-input totp-input"
            id="totp-code"
            type="text"
            inputmode="numeric"
            pattern="[0-9]*"
            maxlength="6"
            placeholder="000000"
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
          {totpLoading ? 'Verifying...' : 'Verify'}
        </button>
      </form>

      <button class="btn-back" onclick={backToCredentials}>
        ← Back to sign in
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
