<script lang="ts">
  import { currentUser } from '../lib/authStore';
  import { t } from '../lib/i18n';

  const STORAGE_KEY = 'announcement_dismissed';

  let dismissed = $state(sessionStorage.getItem(STORAGE_KEY) === ($currentUser?.announcement ?? ''));

  // On a demo instance the banner is not a notice but a standing fact about
  // the install: everyone who signs in shares one account and one set of data.
  // So it is always on and carries no dismiss button — a fact you can close is
  // a fact the next person never sees. A deployer's own ANNOUNCEMENT still
  // wins as the text, since they may have something more specific to say.
  let isDemo = $derived($currentUser?.demo === true);
  let message = $derived($currentUser?.announcement || (isDemo ? $t('demo.banner') : ''));

  function dismiss() {
    sessionStorage.setItem(STORAGE_KEY, $currentUser?.announcement ?? '');
    dismissed = true;
  }
</script>

{#if message && (isDemo || !dismissed)}
  <div class="announcement-banner">
    <span>{message}</span>
    {#if !isDemo}
      <button onclick={dismiss} aria-label="Dismiss">✕</button>
    {/if}
  </div>
{/if}

<style>
  .announcement-banner {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-md);
    padding: 0.5rem var(--space-lg);
    /* --accent is a greyscale value, so the text on it has to be --accent-on:
       hardcoded #fff was white on white the moment the palette went dark. */
    background: var(--accent);
    color: var(--accent-on);
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
    color: var(--accent-on);
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
