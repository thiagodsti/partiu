<script lang="ts">
  // svelte-spa-router provides the current location as a store
  import { location } from 'svelte-spa-router';
  import { t } from '../lib/i18n';
</script>

<nav class="tab-bar">
  <a
    class="tab-item"
    class:active={$location === '/' || $location.startsWith('/trips')}
    href="#/trips"
  >
    <span class="tab-icon">✈</span>
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
    class:active={$location.startsWith('/settings')}
    href="#/settings"
  >
    <span class="tab-icon">⚙︎</span>
    <span>{$t('nav.settings')}</span>
  </a>
</nav>
