<script lang="ts">
  import type { Flight } from '../api/types';
  import { legStats, formatDuration } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    label: string;
    flights: Flight[];
  }
  const { label, flights }: Props = $props();

  const stats = $derived(legStats(flights));
  const flyingStr = $derived(formatDuration(stats.flyingMinutes));
  const totalStr = $derived(formatDuration(stats.totalMinutes));
  const info = $derived(
    stats.flyingMinutes > 0
      ? ` · ${flyingStr} ${$t('trip.flying')}${stats.totalMinutes > stats.flyingMinutes ? ` · ${totalStr} ${$t('trip.total')}` : ''}`
      : ''
  );
</script>

<div class="section-divider" style="margin-top:var(--space-lg)">
  <div class="section-divider-line"></div>
  <span class="section-divider-label">{label}{info}</span>
  <div class="section-divider-line"></div>
</div>
