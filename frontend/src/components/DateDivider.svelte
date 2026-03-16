<script lang="ts">
  import type { Flight } from '../api/types';
  import { dateDividerInfo } from '../lib/utils';

  interface Props {
    prev: Flight;
    next: Flight;
  }
  const { prev, next }: Props = $props();

  const info = $derived(dateDividerInfo(prev, next));
</script>

{#if info}
  <div class="date-divider">
    <div class="date-divider-line"></div>
    <span class="date-divider-label">{info.label}</span>
    <div class="date-divider-line"></div>
  </div>
{/if}
