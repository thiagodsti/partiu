<script lang="ts">
  import { usersApi } from '../api/client';
  import { currentUser } from '../lib/authStore';
  import type { UserListItem } from '../api/types';
  import TopNav from '../components/TopNav.svelte';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import { t } from '../lib/i18n';

  let users = $state<UserListItem[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let msg = $state('');
  let msgType = $state<'success' | 'error'>('success');

  // New user form
  let newUsername = $state('');
  let newPassword = $state('');
  let newIsAdmin = $state(false);
  let newSmtpRecipient = $state('');
  let creating = $state(false);

  // Reset password
  let resetUserId = $state<number | null>(null);
  let resetPassword = $state('');
  let resetting = $state(false);

  async function load() {
    loading = true;
    error = null;
    try {
      users = await usersApi.list();
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  function showMsg(text: string, type: 'success' | 'error' = 'success') {
    msg = text;
    msgType = type;
    setTimeout(() => { msg = ''; }, 4000);
  }

  async function createUser(e: Event) {
    e.preventDefault();
    if (!newUsername.trim() || !newPassword) return;
    creating = true;
    try {
      await usersApi.create({
        username: newUsername.trim(),
        password: newPassword,
        is_admin: newIsAdmin,
        smtp_recipient_address: newSmtpRecipient.trim() || undefined,
      });
      showMsg($t('users.created', { values: { name: newUsername.trim() } }));
      newUsername = '';
      newPassword = '';
      newIsAdmin = false;
      newSmtpRecipient = '';
      await load();
    } catch (err) {
      showMsg((err as Error).message, 'error');
    } finally {
      creating = false;
    }
  }

  async function deleteUser(u: UserListItem) {
    if (!confirm($t('users.delete_confirm', { values: { name: u.username } }))) return;
    try {
      await usersApi.delete(u.id);
      showMsg($t('users.deleted', { values: { name: u.username } }));
      await load();
    } catch (err) {
      showMsg((err as Error).message, 'error');
    }
  }

  async function resetUserPassword(userId: number) {
    if (!resetPassword || resetPassword.length < 8) {
      showMsg($t('users.err_pw_short'), 'error');
      return;
    }
    resetting = true;
    try {
      await usersApi.update(userId, { new_password: resetPassword });
      showMsg($t('users.pw_updated'));
      resetUserId = null;
      resetPassword = '';
    } catch (err) {
      showMsg((err as Error).message, 'error');
    } finally {
      resetting = false;
    }
  }

</script>

<TopNav title={$t('users.title')} />

<div class="main-content">
  {#if loading}
    <LoadingScreen icon="👤" message={$t('users.loading')} />
  {:else if error}
    <EmptyState icon="⚠️" title={$t('users.load_error')} description={error} />
  {:else}
    {#if msg}
      <div class="msg-banner {msgType}">{msg}</div>
    {/if}

    <!-- User list -->
    <div class="settings-section">
      <div class="settings-section-title">{$t('users.all_users')}</div>

      {#if users.length === 0}
        <p style="color: var(--text-secondary); font-size: 0.875rem;">{$t('users.none')}</p>
      {:else}
        <div class="user-list">
          {#each users as u (u.id)}
            <div class="user-row">
              <div class="user-info">
                <span class="user-name">{u.username}</span>
                {#if u.is_admin}
                  <span class="badge-admin">{$t('users.badge_admin')}</span>
                {/if}
                {#if u.totp_enabled}
                  <span class="badge-2fa">{$t('users.badge_2fa')}</span>
                {/if}
                {#if u.smtp_recipient_address}
                  <span class="user-email">{u.smtp_recipient_address}</span>
                {/if}
              </div>
              <div class="user-actions">
                {#if u.id !== $currentUser?.id}
                  <button
                    class="btn btn-secondary btn-sm"
                    onclick={() => { resetUserId = resetUserId === u.id ? null : u.id; resetPassword = ''; }}
                  >
                    {$t('users.reset_pw')}
                  </button>
                  <button
                    class="btn btn-sm"
                    style="border-color: var(--danger); color: var(--danger);"
                    onclick={() => deleteUser(u)}
                  >
                    {$t('users.delete')}
                  </button>
                {:else}
                  <span style="font-size: 0.75rem; color: var(--text-muted);">{$t('users.badge_you')}</span>

                {/if}
              </div>
            </div>

            {#if resetUserId === u.id}
              <div class="reset-form">
                <input
                  class="form-input"
                  type="password"
                  bind:value={resetPassword}
                  placeholder={$t('users.new_pw_placeholder')}
                  style="margin-bottom: var(--space-sm);"
                />
                <div style="display: flex; gap: var(--space-sm);">
                  <button
                    class="btn btn-primary btn-sm"
                    disabled={resetting}
                    onclick={() => resetUserPassword(u.id)}
                  >
                    {resetting ? $t('users.btn_saving_pw') : $t('users.btn_save_pw')}
                  </button>
                  <button
                    class="btn btn-secondary btn-sm"
                    onclick={() => { resetUserId = null; resetPassword = ''; }}
                  >
                    {$t('users.btn_cancel')}
                  </button>
                </div>
              </div>
            {/if}
          {/each}
        </div>
      {/if}
    </div>

    <!-- Create user form -->
    <div class="settings-section">
      <div class="settings-section-title">{$t('users.add_user')}</div>
      <form onsubmit={createUser}>
        <div class="form-group">
          <label class="form-label" for="new-username">{$t('users.new_username')}</label>
          <input
            class="form-input"
            id="new-username"
            type="text"
            bind:value={newUsername}
            placeholder="username"
            minlength="2"
            required
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="new-password">{$t('users.new_password')}</label>
          <input
            class="form-input"
            id="new-password"
            type="password"
            bind:value={newPassword}
            placeholder={$t('users.new_password_placeholder')}
            minlength="8"
            required
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="new-smtp">{$t('users.new_recipient')} <span style="color:var(--text-muted);font-weight:400;font-size:0.8em;">(optional)</span></label>
          <input
            class="form-input"
            id="new-smtp"
            type="email"
            bind:value={newSmtpRecipient}
            placeholder={$t('users.new_recipient_placeholder')}
          />
        </div>

        <div class="form-group">
          <label class="form-label" style="display: flex; align-items: center; gap: var(--space-sm);">
            <input type="checkbox" bind:checked={newIsAdmin} style="width: auto; margin: 0;" />
            {$t('users.grant_admin')}
          </label>
        </div>

        <button class="btn btn-primary" type="submit" disabled={creating}>
          {creating ? $t('users.btn_adding') : $t('users.btn_add')}
        </button>
      </form>
    </div>
  {/if}
</div>

<style>
  .msg-banner {
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-sm);
    margin-bottom: var(--space-md);
    font-size: 0.875rem;
  }
  .msg-banner.success {
    color: var(--success);
    background: color-mix(in srgb, var(--success) 12%, transparent);
  }
  .msg-banner.error {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 12%, transparent);
  }

  .user-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .user-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-sm) var(--space-md);
    background: var(--bg-primary);
    border-radius: var(--radius-sm);
    gap: var(--space-md);
  }

  .user-info {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    flex-wrap: wrap;
    min-width: 0;
  }

  .user-name {
    font-weight: 600;
  }

  .user-email {
    font-size: 0.75rem;
    color: var(--text-muted);
  }

  .badge-admin {
    font-size: 0.7rem;
    font-weight: 600;
    background: var(--accent);
    color: #fff;
    padding: 2px 6px;
    border-radius: 10px;
    text-transform: uppercase;
  }

  .badge-2fa {
    font-size: 0.7rem;
    font-weight: 600;
    background: var(--success);
    color: #fff;
    padding: 2px 6px;
    border-radius: 10px;
  }

  .user-actions {
    display: flex;
    gap: var(--space-xs);
    flex-shrink: 0;
  }

  .btn-sm {
    padding: 4px 10px;
    font-size: 0.8rem;
  }

  .reset-form {
    padding: var(--space-sm) var(--space-md);
    background: var(--bg-primary);
    border-radius: var(--radius-sm);
    border-left: 3px solid var(--accent);
    margin-top: calc(-1 * var(--space-sm));
    margin-bottom: var(--space-xs);
  }
</style>
