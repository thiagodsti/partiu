<script lang="ts">
  import { authApi } from '../api/client';
  import { currentUser } from '../lib/authStore';

  let username = $state('');
  let password = $state('');
  let confirmPassword = $state('');
  let smtpRecipient = $state('');
  let loading = $state(false);
  let error = $state<string | null>(null);

  async function handleSetup(e: Event) {
    e.preventDefault();
    if (!username.trim() || !password) return;

    if (password !== confirmPassword) {
      error = 'Passwords do not match';
      return;
    }
    if (password.length < 6) {
      error = 'Password must be at least 6 characters';
      return;
    }

    loading = true;
    error = null;
    try {
      const user = await authApi.setup({
        username: username.trim(),
        password,
        smtp_recipient_address: smtpRecipient.trim() || undefined,
      });
      currentUser.set(user);
      window.location.hash = '/trips';
    } catch (err) {
      error = (err as Error).message || 'Setup failed';
    } finally {
      loading = false;
    }
  }
</script>

<div class="auth-page">
  <div class="auth-card">
    <div class="auth-logo">✈</div>
    <h1 class="auth-title">Welcome to Partiu</h1>
    <p class="auth-subtitle">Create your admin account to get started</p>

    <form onsubmit={handleSetup}>
      <div class="form-group">
        <label class="form-label" for="setup-username">Username</label>
        <input
          class="form-input"
          id="setup-username"
          type="text"
          bind:value={username}
          placeholder="admin"
          autocomplete="username"
          minlength="2"
          required
        />
      </div>

      <div class="form-group">
        <label class="form-label" for="setup-password">Password</label>
        <input
          class="form-input"
          id="setup-password"
          type="password"
          bind:value={password}
          placeholder="At least 6 characters"
          autocomplete="new-password"
          minlength="6"
          required
        />
      </div>

      <div class="form-group">
        <label class="form-label" for="setup-confirm">Confirm Password</label>
        <input
          class="form-input"
          id="setup-confirm"
          type="password"
          bind:value={confirmPassword}
          placeholder="Repeat password"
          autocomplete="new-password"
          required
        />
      </div>

      <div class="form-group">
        <label class="form-label" for="setup-smtp">Email recipient address <span class="optional">(optional)</span></label>
        <input
          class="form-input"
          id="setup-smtp"
          type="email"
          bind:value={smtpRecipient}
          placeholder="trips@yourdomain.com"
        />
        <div class="form-hint">
          If using the inbound SMTP server, forward flight emails to this address.
        </div>
      </div>

      {#if error}
        <div class="auth-error">{error}</div>
      {/if}

      <button class="btn btn-primary btn-full" type="submit" disabled={loading}>
        {loading ? 'Creating account...' : 'Create Admin Account'}
      </button>
    </form>
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
    max-width: 400px;
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

  .optional {
    color: var(--text-muted);
    font-weight: 400;
    font-size: 0.8em;
  }

  .auth-error {
    color: var(--danger);
    font-size: 0.875rem;
    margin-bottom: var(--space-md);
    padding: var(--space-sm);
    background: color-mix(in srgb, var(--danger) 12%, transparent);
    border-radius: var(--radius-sm);
  }
</style>
