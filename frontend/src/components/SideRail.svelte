<script lang="ts">
  import { location } from 'svelte-spa-router';
  import { t } from '../lib/i18n';
  import { totalInboxBadge } from '../lib/invitationStore';
  import { NAV_ITEMS, isActive } from '../lib/nav';
  import Icon from './Icon.svelte';

  /**
   * Desktop navigation. The bottom tab bar is a phone pattern — on a wide
   * screen it put five targets at the far edge of the screen and wasted a
   * full-width strip of it. The rail is always visible, costs 78px, and
   * leaves the whole page height for content.
   *
   * Hidden under 900px by CSS, where TabBar takes over.
   */
</script>

<nav class="rail" aria-label={$t('nav.trips')}>
  <span class="rail-mark" aria-hidden="true">P</span>

  {#each NAV_ITEMS as item (item.href)}
    <a
      class="nav-item rail-item"
      class:active={isActive(item, $location)}
      href={item.href}
      title={$t(item.label)}
    >
      <span class="rail-glyph">
        <Icon name={item.icon} size={21} />
        {#if item.badge && $totalInboxBadge > 0}
          <span class="nav-badge rail-badge">{$totalInboxBadge}</span>
        {/if}
      </span>
      <span class="rail-label">{$t(item.label)}</span>
    </a>
  {/each}
</nav>

<style>
  .rail-badge {
    position: absolute;
    top: -5px;
    right: -8px;
    background: var(--danger);
    color: #fff;
    border-radius: 999px;
    font-size: 0.6rem;
    min-width: 15px;
    height: 15px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 4px;
    font-weight: 700;
    line-height: 1;
  }
</style>
