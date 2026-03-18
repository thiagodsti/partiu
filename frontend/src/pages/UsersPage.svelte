<script lang="ts">
  import { usersApi } from '../api/client';
  import { currentUser } from '../lib/authStore';
  import type { UserListItem } from '../api/types';
  import TopNav from '../components/TopNav.svelte';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import EmptyState from '../components/EmptyState.svelte';

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
      showMsg(`User "${newUsername.trim()}" created`);
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
    if (!confirm(`Delete user "${u.username}"? This cannot be undone.`)) return;
    try {
      await usersApi.delete(u.id);
      showMsg(`User "${u.username}" deleted`);
      await load();
    } catch (err) {
      showMsg((err as Error).message, 'error');
    }
  }

  async function resetUserPassword(userId: number) {
    if (!resetPassword || resetPassword.length < 6) {
      showMsg('Password must be at least 6 characters', 'error');
      return;
    }
    resetting = true;
    try {
      await usersApi.update(userId, { new_password: resetPassword });
      showMsg('Password updated');
      resetUserId = null;
      resetPassword = '';
    } catch (err) {
      showMsg((err as Error).message, 'error');
    } finally {
      resetting = false;
    }
  }

</script>

<TopNav title="Users" />

<div class="main-content">
  {#if loading}
    <LoadingScreen icon="👤" message="Loading users..." />
  {:else if error}
    <EmptyState icon="⚠️" title="Failed to load users" description={error} />
  {:else}
    {#if msg}
      <div class="msg-banner {msgType}">{msg}</div>
    {/if}

    <!-- User list -->
    <div class="settings-section">
      <div class="settings-section-title">All Users</div>

      {#if users.length === 0}
        <p style="color: var(--text-secondary); font-size: 0.875rem;">No users found.</p>
      {:else}
        <div class="user-list">
          {#each users as u (u.id)}
            <div class="user-row">
              <div class="user-info">
                <span class="user-name">{u.username}</span>
                {#if u.is_admin}
                  <span class="badge-admin">Admin</span>
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
                    Reset PW
                  </button>
                  <button
                    class="btn btn-sm"
                    style="border-color: var(--danger); color: var(--danger);"
                    onclick={() => deleteUser(u)}
                  >
                    Delete
                  </button>
                {:else}
                  <span style="font-size: 0.75rem; color: var(--text-muted);">(you)</span>

                {/if}
              </div>
            </div>

            {#if resetUserId === u.id}
              <div class="reset-form">
                <input
                  class="form-input"
                  type="password"
                  bind:value={resetPassword}
                  placeholder="New password (min 6 chars)"
                  style="margin-bottom: var(--space-sm);"
                />
                <div style="display: flex; gap: var(--space-sm);">
                  <button
                    class="btn btn-primary btn-sm"
                    disabled={resetting}
                    onclick={() => resetUserPassword(u.id)}
                  >
                    {resetting ? 'Saving...' : 'Save Password'}
                  </button>
                  <button
                    class="btn btn-secondary btn-sm"
                    onclick={() => { resetUserId = null; resetPassword = ''; }}
                  >
                    Cancel
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
      <div class="settings-section-title">Add User</div>
      <form onsubmit={createUser}>
        <div class="form-group">
          <label class="form-label" for="new-username">Username</label>
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
          <label class="form-label" for="new-password">Password</label>
          <input
            class="form-input"
            id="new-password"
            type="password"
            bind:value={newPassword}
            placeholder="At least 6 characters"
            minlength="6"
            required
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="new-smtp">Email recipient address <span style="color:var(--text-muted);font-weight:400;font-size:0.8em;">(optional)</span></label>
          <input
            class="form-input"
            id="new-smtp"
            type="email"
            bind:value={newSmtpRecipient}
            placeholder="trips@yourdomain.com"
          />
        </div>

        <div class="form-group">
          <label class="form-label" style="display: flex; align-items: center; gap: var(--space-sm);">
            <input type="checkbox" bind:checked={newIsAdmin} style="width: auto; margin: 0;" />
            Grant admin privileges
          </label>
        </div>

        <button class="btn btn-primary" type="submit" disabled={creating}>
          {creating ? 'Creating...' : '+ Add User'}
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
