<script lang="ts">
  import { toasts } from '../lib/toastStore';
</script>

{#if $toasts.length > 0}
  <div class="toast-container">
    {#each $toasts as toast (toast.id)}
      <div class="toast toast-{toast.type}">{toast.message}</div>
    {/each}
  </div>
{/if}
