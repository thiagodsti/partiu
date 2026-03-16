<script lang="ts">
  import type { Flight } from '../api/types';
  import { connectionInfo } from '../lib/utils';

  interface Props {
    prev: Flight;
    next: Flight;
  }
  const { prev, next }: Props = $props();

  const info = $derived(connectionInfo(prev, next));
</script>

{#if info}
  <div class="connection-badge">
    <div class="connection-badge-line"></div>
    <span class="connection-badge-label">⏱ {info.label} at {info.airport}</span>
    <div class="connection-badge-line"></div>
  </div>
{/if}
