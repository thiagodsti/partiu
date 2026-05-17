<script lang="ts">
  interface DataPoint {
    label: string;
    count: number;
  }

  interface Props {
    data: DataPoint[];
  }

  const { data }: Props = $props();

  const CHART_H = 100;
  const BAR_W = 24;
  const GAP = 6;
  const LABEL_H = 18;
  const COUNT_H = 14;  // space above bars for count labels
  const SVG_H = COUNT_H + CHART_H + LABEL_H;

  const maxCount = $derived(Math.max(...data.map((d) => d.count), 1));
  const svgW = $derived(data.length * (BAR_W + GAP) - GAP);

  function barHeight(count: number): number {
    return (count / maxCount) * CHART_H;
  }

  function barY(count: number): number {
    return COUNT_H + CHART_H - barHeight(count);
  }

  // "2024-03" → "Mar" (locale-aware), "2024" → "2024"
  function periodLabel(label: string): string {
    if (label.length === 7) {
      const [y, m] = label.split('-');
      const d = new Date(+y, +m - 1, 1);
      return d.toLocaleDateString(undefined, { month: 'short' });
    }
    return label;
  }

  // Show only every Nth label so they don't overlap when there are many bars
  function showLabel(i: number): boolean {
    if (data.length <= 12) return true;
    const step = data.length <= 24 ? 2 : 3;
    return i % step === 0;
  }
</script>

<div class="chart-scroll">
  <svg
    viewBox="0 0 {svgW} {SVG_H}"
    width={svgW}
    height={SVG_H}
    aria-label="Flights per period bar chart"
    role="img"
  >
    {#each data as d, i}
      {@const x = i * (BAR_W + GAP)}
      {@const bh = barHeight(d.count)}
      {@const by = barY(d.count)}
      <rect
        x={x}
        y={by}
        width={BAR_W}
        height={bh}
        rx="3"
        class="chart-bar"
        class:chart-bar-empty={d.count === 0}
      />
      {#if d.count > 0}
        <text
          x={x + BAR_W / 2}
          y={by - 3}
          text-anchor="middle"
          class="chart-count"
        >{d.count}</text>
      {/if}
      {#if showLabel(i)}
        <text
          x={x + BAR_W / 2}
          y={SVG_H}
          text-anchor="middle"
          class="chart-label"
        >{periodLabel(d.label)}</text>
      {/if}
    {/each}
  </svg>
</div>

<style>
  .chart-scroll {
    overflow-x: auto;
    padding-bottom: 0.25rem;
  }

  .chart-scroll svg {
    display: block;
    min-width: 100%;
  }

  .chart-bar {
    fill: var(--accent, #6366f1);
    opacity: 0.85;
  }

  .chart-bar-empty {
    fill: var(--border, #334155);
    opacity: 0.4;
    height: 2px;
  }

  .chart-count {
    font-size: 9px;
    fill: var(--text-muted, #94a3b8);
    font-variant-numeric: tabular-nums;
  }

  .chart-label {
    font-size: 9px;
    fill: var(--text-muted, #94a3b8);
  }
</style>
