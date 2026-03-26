<script lang="ts">
  // svelte-spa-router provides the current location as a store
  import { location } from 'svelte-spa-router';
  import { t } from '../lib/i18n';
  import { pendingInvitationCount } from '../lib/invitationStore';
</script>

<nav class="tab-bar">
  <a
    class="tab-item"
    class:active={$location === '/' || $location.startsWith('/trips')}
    href="#/trips"
  >
    <span class="tab-icon">✈︎</span>
    <span>{$t('nav.trips')}</span>
  </a>
  <a
    class="tab-item"
    class:active={$location.startsWith('/history')}
    href="#/history"
  >
    <span class="tab-icon">◷</span>
    <span>{$t('nav.history')}</span>
  </a>
  <a
    class="tab-item"
    class:active={$location.startsWith('/stats')}
    href="#/stats"
  >
    <span class="tab-icon">★︎</span>
    <span>{$t('nav.stats')}</span>
  </a>
  <a
    class="tab-item"
    class:active={$location.startsWith('/invitations')}
    href="#/invitations"
    style="position:relative"
  >
    <span class="tab-icon">
      ✉︎
      {#if $pendingInvitationCount > 0}
        <span class="tab-badge">{$pendingInvitationCount}</span>
      {/if}
    </span>
    <span>{$t('nav.invitations')}</span>
  </a>
  <a
    class="tab-item"
    class:active={$location.startsWith('/settings')}
    href="#/settings"
  >
    <span class="tab-icon">⚙︎</span>
    <span>{$t('nav.settings')}</span>
  </a>
</nav>

<style>
  .tab-badge {
    position: absolute;
    top: -4px;
    right: -6px;
    background: var(--danger, #ef4444);
    color: #fff;
    border-radius: 999px;
    font-size: 0.6rem;
    min-width: 14px;
    height: 14px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 3px;
    font-weight: 700;
    line-height: 1;
  }

  .tab-item .tab-icon {
    position: relative;
    display: inline-block;
  }
</style>
