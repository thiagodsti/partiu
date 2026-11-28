<script lang="ts">
  /**
   * Settings → AI suggestions: whether the planner's suggestions may read the
   * traveller's past trips. Rendered only when the server has a provider set
   * up — a switch for a feature that does not exist here would only confuse.
   * Off by default; the hint says exactly what is sent, because trip notes are
   * free text and go to an outside service.
   */
  import { suggestionsApi } from '../api/client';
  import type { SuggestionsStatus } from '../api/types';
  import { t } from '../lib/i18n';
  import { toasts } from '../lib/toastStore';

  let status = $state<SuggestionsStatus | null>(null);
  let saving = $state(false);

  suggestionsApi
    .status()
    .then((s) => (status = s))
    .catch(() => (status = null));

  async function toggle(value: boolean) {
    if (!status) return;
    const prev = status.use_history;
    status.use_history = value;
    saving = true;
    try {
      await suggestionsApi.setUseHistory(value);
    } catch (err) {
      status.use_history = prev;
      toasts.show((err as Error).message, 'error');
    } finally {
      saving = false;
    }
  }
</script>

{#if status?.available}
  <div class="settings-section" data-testid="ai-suggestions-settings">
    <div class="settings-section-title">✨ {$t('suggest.settings_title')}</div>
    <label class="ai-row">
      <input
        type="checkbox"
        checked={status.use_history}
        disabled={saving}
        onchange={(e) => toggle((e.currentTarget as HTMLInputElement).checked)}
      />
      <span>{$t('suggest.settings_use_history')}</span>
    </label>
    <p class="ai-hint">{$t('suggest.settings_use_history_hint')}</p>
    <p class="ai-hint">
      {$t('suggest.settings_usage', { values: { used: status.used_today, limit: status.daily_limit } })}
    </p>
  </div>
{/if}

<style>
  .ai-row {
    display: flex;
    align-items: flex-start;
    gap: var(--space-sm);
    cursor: pointer;
  }
  .ai-row input {
    flex-shrink: 0;
    width: 1rem;
    height: 1rem;
    margin: 2px 0 0;
  }
  .ai-hint {
    margin: var(--space-xs, 4px) 0 0;
    font-size: 0.8rem;
    color: var(--text-muted);
  }
</style>
