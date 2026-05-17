<script lang="ts">
  import { isOnline } from '../lib/onlineStore';
</script>

{#if !$isOnline}
  <div class="offline-banner" role="status" aria-live="polite">
    <span class="offline-icon">⚡</span>
    <span>You're offline — showing cached data</span>
  </div>
{/if}

<style>
  .offline-banner {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.4rem var(--space-lg, 1rem);
    background: #92400e;
    color: #fef3c7;
    font-size: 0.8125rem;
    text-align: center;
    position: sticky;
    top: 0;
    z-index: 101;
  }

  .offline-icon {
    font-size: 0.875rem;
    line-height: 1;
  }
</style>
