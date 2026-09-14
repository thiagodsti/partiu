<script lang="ts">
  import { authApi } from "../api/client";
  import { currentUser } from "../lib/authStore";
  import { pendingInvitationCount } from "../lib/invitationStore";
  import { t } from "../lib/i18n";

  /**
   * The sign over the concourse: where you are, set large, with the way back
   * on the left and who you are on the right. Sticky, because on a phone it
   * is the only thing that names the current page once the list scrolls.
   *
   * `actions` lets a page hang its own controls next to the title instead of
   * dropping them into the content, which is where they used to live.
   */
  interface Props {
    title: string;
    backHref?: string | null;
    actions?: import('svelte').Snippet;
  }
  const { title, backHref = null, actions }: Props = $props();

  let loggingOut = $state(false);

  async function handleLogout() {
    loggingOut = true;
    try {
      await authApi.logout();
    } catch {
      // ignore
    }
    currentUser.set(null);
    pendingInvitationCount.set(0);
    window.location.hash = "/login";
    loggingOut = false;
  }
</script>

<nav class="top-nav">
  <div class="nav-inner">
    {#if backHref}
      <a class="nav-back" href={backHref} aria-label={$t("trip.back")}>←</a>
    {/if}
    <h1 class="nav-title">{title}</h1>
    {#if actions}
      <div class="nav-actions">{@render actions()}</div>
    {/if}
    {#if $currentUser}
      <span class="nav-user">
        <span class="nav-username">{$currentUser.username}</span>
        <button
          class="nav-logout"
          onclick={handleLogout}
          disabled={loggingOut}
          title={$t("signout")}
          aria-label={$t("signout")}
        >
          {loggingOut ? "…" : "↩"}
        </button>
      </span>
    {/if}
  </div>
</nav>

<style>
  .nav-actions {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    flex-shrink: 0;
  }

  /* Under 560px the username is the first thing to go: the title and the
     sign-out control both have jobs, and the username is only a reminder
     of which account is open. */
  @media (max-width: 560px) {
    .nav-username {
      display: none;
    }

    .nav-user {
      padding-left: 3px;
    }
  }
</style>
