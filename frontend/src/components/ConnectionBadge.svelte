<script lang="ts">
  import type { TransportLeg } from '../lib/utils';
  import { connectionInfo } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    prev: TransportLeg;
    next: TransportLeg;
  }
  const { prev, next }: Props = $props();

  const info = $derived(connectionInfo(prev, next));
</script>

{#if info}
  <div class="connection-badge">
    <div class="connection-badge-line"></div>
    <span class="connection-badge-label">⏱ {$t('connection.layover', { values: { label: info.label, airport: info.place } })}</span>
    <div class="connection-badge-line"></div>
  </div>
{/if}
