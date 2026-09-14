<script lang="ts">
  // svelte-spa-router provides the current location as a store
  import { location } from 'svelte-spa-router';
  import { t } from '../lib/i18n';
  import { totalInboxBadge } from '../lib/invitationStore';
  import { NAV_ITEMS, isActive } from '../lib/nav';
  import Icon from './Icon.svelte';

  /**
   * Phone navigation: a floating dock rather than a full-width bar pinned to
   * the bottom edge. The page scrolls visibly underneath it, so the list does
   * not appear to end where the bar starts. Hidden from 900px up, where
   * SideRail takes over.
   */
</script>

<nav class="tab-bar">
  {#each NAV_ITEMS as item (item.href)}
    <a class="nav-item tab-item" class:active={isActive(item, $location)} href={item.href}>
      <span class="tab-icon">
        <Icon name={item.icon} size={19} />
        {#if item.badge && $totalInboxBadge > 0}
          <span class="nav-badge tab-badge">{$totalInboxBadge}</span>
        {/if}
      </span>
      <span>{$t(item.label)}</span>
    </a>
  {/each}
</nav>

<style>
  .tab-icon {
    position: relative;
    display: inline-flex;
  }

  .tab-badge {
    position: absolute;
    top: -5px;
    right: -8px;
    background: var(--danger);
    color: #fff;
    border-radius: 999px;
    font-size: 0.58rem;
    min-width: 14px;
    height: 14px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 3px;
    font-weight: 700;
    line-height: 1;
  }

  /* The active tab is a filled amber chip — on a dark dock a colour change
     alone is easy to miss at a glance, and the fill matches the primary
     button, so "the thing that is lit is the thing you are on". */
  .tab-item.active .tab-badge {
    border: 1px solid var(--accent);
  }
</style>
