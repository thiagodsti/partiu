<script lang="ts">
  import { authApi } from "../api/client";
  import { currentUser } from "../lib/authStore";
  import { pendingInvitationCount } from "../lib/invitationStore";
  import { t } from "svelte-i18n";

  interface Props {
    title: string;
    backHref?: string | null;
  }
  const { title, backHref = null }: Props = $props();

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
  {#if backHref}
    <a class="nav-back" href={backHref}>←</a>
  {/if}
  <span class="nav-title">{title}</span>
  {#if $currentUser}
    <span class="nav-username">{$currentUser.username}</span>
    <button
      class="nav-logout"
      onclick={handleLogout}
      disabled={loggingOut}
      title={$t("signout")}
    >
      {loggingOut ? "..." : "↩"}
    </button>
  {/if}
</nav>

<style>
  .nav-username {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-right: var(--space-xs);
  }

  .nav-logout {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-secondary);
    font-size: 1rem;
    padding: 4px 6px;
    border-radius: var(--radius-sm);
    line-height: 1;
    transition:
      color 0.15s,
      background 0.15s;
  }

  .nav-logout:hover:not(:disabled) {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
  }

  .nav-logout:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
