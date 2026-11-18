<script lang="ts">
  import { onMount } from 'svelte';
  import { apiKeysApi } from '../api/client';
  import type { ApiKey, ApiKeyScope, CreatedApiKey } from '../api/types';
  import { formatDate } from '../lib/utils';
  import { t } from '../lib/i18n';

  /** A demo account is shared by every visitor, so the backend refuses to mint
   * keys there; the form is hidden rather than left to fail. */
  let { demo = false }: { demo?: boolean } = $props();

  const EXPIRY_OPTIONS: { days: number | null; label: string }[] = [
    { days: 30, label: 'api_keys.expires_30' },
    { days: 90, label: 'api_keys.expires_90' },
    { days: 365, label: 'api_keys.expires_365' },
    { days: null, label: 'api_keys.expires_never' },
  ];

  let keys = $state<ApiKey[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let name = $state('');
  let scope = $state<ApiKeyScope>('read');
  // Kept as a string because <select> values are strings; '' means never.
  let expiry = $state('90');
  let creating = $state(false);
  let busyId = $state<number | null>(null);

  /** The key just minted — the one moment its value exists in the browser. */
  let created = $state<CreatedApiKey | null>(null);
  let copied = $state(false);

  async function reload() {
    loading = true;
    error = null;
    try {
      keys = await apiKeysApi.list();
    } catch (err) {
      error = (err as Error)?.message ?? String(err);
    } finally {
      loading = false;
    }
  }

  async function create(e: Event) {
    e.preventDefault();
    if (!name.trim() || loading) return;
    creating = true;
    error = null;
    try {
      const result = await apiKeysApi.create({
        name: name.trim(),
        scope,
        expires_in_days: expiry ? Number(expiry) : null,
      });
      created = result;
      copied = false;
      const { key: _secret, ...listed } = result;
      keys = [listed, ...keys];
      name = '';
    } catch (err) {
      error = (err as Error)?.message ?? String(err);
    } finally {
      creating = false;
    }
  }

  async function copy() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.key);
      copied = true;
    } catch {
      // No clipboard access (insecure context, permission denied): the key is
      // still selectable in the field above.
      copied = false;
    }
  }

  async function revoke(key: ApiKey) {
    if (!confirm($t('api_keys.revoke_confirm', { values: { name: key.name } }))) return;
    busyId = key.id;
    error = null;
    try {
      await apiKeysApi.revoke(key.id);
      keys = keys.filter((k) => k.id !== key.id);
      if (created?.id === key.id) created = null;
    } catch (err) {
      error = (err as Error)?.message ?? String(err);
    } finally {
      busyId = null;
    }
  }

  function isExpired(key: ApiKey): boolean {
    return !!key.expires_at && new Date(key.expires_at).getTime() <= Date.now();
  }

  onMount(() => {
    void reload();
  });
</script>

<div class="settings-section api-keys-panel">
  <div class="settings-section-title">{$t('api_keys.title')}</div>
  <p class="text-muted api-keys-desc">{$t('api_keys.desc')}</p>
  <code class="api-keys-usage">Authorization: Bearer partiu_…</code>

  {#if error}
    <p class="api-keys-error" role="alert">{error}</p>
  {/if}

  {#if created}
    <div class="api-keys-created" role="status">
      <p class="api-keys-created-warning">{$t('api_keys.created_once')}</p>
      <div class="api-keys-created-row">
        <input
          class="form-input api-keys-secret"
          type="text"
          readonly
          value={created.key}
          aria-label={$t('api_keys.secret_label')}
          onfocus={(e) => (e.currentTarget as HTMLInputElement).select()}
        />
        <button type="button" class="btn btn-secondary btn-sm" onclick={copy}>
          {copied ? $t('api_keys.copied') : $t('api_keys.copy')}
        </button>
        <button type="button" class="btn btn-secondary btn-sm" onclick={() => (created = null)}>
          {$t('api_keys.done')}
        </button>
      </div>
    </div>
  {/if}

  {#if demo}
    <p class="demo-locked">{$t('demo.locked_api_keys')}</p>
  {:else}
    <form class="api-keys-form" onsubmit={create}>
      <div class="form-row">
        <div class="form-field">
          <label class="form-label" for="api-key-name">{$t('api_keys.name')}</label>
          <input
            class="form-input"
            id="api-key-name"
            type="text"
            maxlength="100"
            placeholder={$t('api_keys.name_placeholder')}
            bind:value={name}
          />
        </div>
        <div class="form-field">
          <label class="form-label" for="api-key-scope">{$t('api_keys.scope')}</label>
          <select
            class="form-input"
            id="api-key-scope"
            value={scope}
            onchange={(e) => (scope = e.currentTarget.value as ApiKeyScope)}
          >
            <option value="read">{$t('api_keys.scope_read')}</option>
            <option value="write">{$t('api_keys.scope_write')}</option>
          </select>
        </div>
        <div class="form-field">
          <label class="form-label" for="api-key-expiry">{$t('api_keys.expires')}</label>
          <select
            class="form-input"
            id="api-key-expiry"
            value={expiry}
            onchange={(e) => (expiry = e.currentTarget.value)}
          >
            {#each EXPIRY_OPTIONS as opt (opt.label)}
              <option value={opt.days === null ? '' : String(opt.days)}>{$t(opt.label)}</option>
            {/each}
          </select>
        </div>
      </div>
      <!-- Not while the list is loading: a key created then would be added to
           the list and wiped by the late response, leaving a live credential
           with no revoke button until the page is reloaded. -->
      <button class="btn btn-primary" type="submit" disabled={creating || loading || !name.trim()}>
        {creating ? $t('api_keys.creating') : $t('api_keys.create')}
      </button>
    </form>
  {/if}

  {#if loading}
    <p class="text-muted">{$t('api_keys.loading')}</p>
  {:else if keys.length === 0}
    <p class="text-muted api-keys-empty">{$t('api_keys.empty')}</p>
  {:else}
    <ul class="api-keys-list">
      {#each keys as key (key.id)}
        <li class="api-keys-item">
          <div class="api-keys-main">
            <span class="api-keys-name">{key.name}</span>
            <span class="api-keys-meta">
              <code>{key.prefix}…</code>
              · {key.scope === 'write' ? $t('api_keys.scope_write') : $t('api_keys.scope_read')}
            </span>
            <span class="text-muted api-keys-meta">
              {$t('api_keys.created_on', { values: { date: formatDate(key.created_at) } })}
              · {key.last_used_at
                ? $t('api_keys.last_used', { values: { date: formatDate(key.last_used_at) } })
                : $t('api_keys.never_used')}
              · {#if !key.expires_at}
                {$t('api_keys.no_expiry')}
              {:else if isExpired(key)}
                <span class="api-keys-expired">{$t('api_keys.expired')}</span>
              {:else}
                {$t('api_keys.expires_on', { values: { date: formatDate(key.expires_at) } })}
              {/if}
            </span>
          </div>
          <button
            class="btn btn-danger btn-sm"
            disabled={busyId === key.id}
            onclick={() => revoke(key)}
          >
            {$t('api_keys.revoke')}
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .api-keys-desc { margin: 0 0 var(--space-xs); font-size: 0.875rem; }
  .api-keys-usage {
    display: inline-block; font-family: var(--font-mono); font-size: 0.8rem;
    margin-bottom: var(--space-md); overflow-wrap: anywhere;
  }
  .api-keys-form { display: flex; flex-direction: column; gap: var(--space-sm); margin-bottom: var(--space-md); }
  .api-keys-form .btn { align-self: flex-start; }
  .api-keys-created {
    border: 1px solid var(--border-strong); border-radius: var(--radius, 8px);
    padding: var(--space-sm); margin-bottom: var(--space-md);
  }
  .api-keys-created-warning { margin: 0 0 var(--space-xs); font-size: 0.875rem; font-weight: 600; }
  .api-keys-created-row { display: flex; flex-wrap: wrap; gap: var(--space-xs); align-items: center; }
  .api-keys-secret { flex: 1 1 260px; min-width: 0; font-family: var(--font-mono); font-size: 0.8rem; }
  .api-keys-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .api-keys-item {
    display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center;
    gap: var(--space-sm); padding: var(--space-sm) 0; border-top: 1px solid var(--border);
  }
  .api-keys-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 220px; }
  .api-keys-name { font-weight: 600; overflow-wrap: anywhere; }
  .api-keys-meta { font-size: 0.8rem; }
  .api-keys-meta code { font-family: var(--font-mono); }
  .api-keys-expired { color: var(--danger-text); }
  .api-keys-empty { margin: 0; font-size: 0.875rem; }
  .api-keys-error { color: var(--danger-text); font-size: 0.875rem; margin: 0 0 var(--space-sm); }
  .demo-locked { margin: 0 0 var(--space-md); font-size: 0.875rem; color: var(--text-muted); }
</style>
