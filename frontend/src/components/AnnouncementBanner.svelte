<script lang="ts">
  import { currentUser } from '../lib/authStore';

  const STORAGE_KEY = 'announcement_dismissed';

  let dismissed = $state(sessionStorage.getItem(STORAGE_KEY) === ($currentUser?.announcement ?? ''));

  function dismiss() {
    sessionStorage.setItem(STORAGE_KEY, $currentUser?.announcement ?? '');
    dismissed = true;
  }
</script>

{#if $currentUser?.announcement && !dismissed}
  <div class="announcement-banner">
    <span>{$currentUser.announcement}</span>
    <button onclick={dismiss} aria-label="Dismiss">✕</button>
  </div>
{/if}

<style>
  .announcement-banner {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-md);
    padding: 0.5rem var(--space-lg);
    background: var(--accent, #6366f1);
    color: #fff;
    font-size: 0.875rem;
    text-align: center;
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .announcement-banner span {
    flex: 1;
  }

  .announcement-banner button {
    background: none;
    border: none;
    color: #fff;
    cursor: pointer;
    font-size: 1rem;
    opacity: 0.8;
    padding: 0 0.25rem;
    line-height: 1;
    flex-shrink: 0;
  }

  .announcement-banner button:hover {
    opacity: 1;
  }
</style>
