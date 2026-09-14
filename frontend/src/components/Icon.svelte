<script lang="ts">
  /**
   * The navigation glyphs. These were text characters (✈︎ ◷ ★︎ ✉︎ ⚙︎), which
   * render at whatever weight and baseline each platform's emoji font decides
   * — the set never looked like one family. Drawn strokes match the UI's own
   * hairlines instead, and inherit currentColor so the active state needs no
   * second asset.
   */
  interface Props {
    name: 'plane' | 'clock' | 'chart' | 'inbox' | 'sliders';
    size?: number;
  }
  const { name, size = 22 }: Props = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.7"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  focusable="false"
>
  {#if name === 'plane'}
    <path d="M21 3 2.5 9.6l7.2 2.7 2.7 7.2L21 3Z" />
    <path d="M9.7 12.3 21 3" />
  {:else if name === 'clock'}
    <path d="M3.2 10.5A9 9 0 1 1 4.6 16" />
    <path d="M3 20v-4.5h4.5" />
    <path d="M12 7.5V12l3 1.8" />
  {:else if name === 'chart'}
    <path d="M4 20V11" />
    <path d="M10 20V4" />
    <path d="M16 20v-6" />
    <path d="M22 20H2" />
  {:else if name === 'inbox'}
    <rect x="2.75" y="5" width="18.5" height="14" rx="2.5" />
    <path d="m3.5 7.5 7.2 5.1a2.2 2.2 0 0 0 2.6 0l7.2-5.1" />
  {:else if name === 'sliders'}
    <path d="M3 7h11" />
    <path d="M18 7h3" />
    <path d="M3 17h5" />
    <path d="M12 17h9" />
    <circle cx="16" cy="7" r="2.2" />
    <circle cx="10" cy="17" r="2.2" />
  {/if}
</svg>
