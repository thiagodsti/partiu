<script lang="ts">
  /**
   * The app's checkbox, used by the packing list and the day planner.
   *
   * Drawn rather than native: `accent-color` on an `<input type="checkbox">`
   * renders differently on every platform and cannot follow the chosen accent
   * preset's ink/white pairing. The two lists each had their own before this —
   * one drawn and accent-coloured, one native and green — which is how they
   * came to look like different controls doing the same job.
   *
   * A `<button role="checkbox">` rather than a styled input: the tick has to be
   * painted in `--accent-on`, and `background-image` cannot reference a CSS
   * variable, so the mark has to be real markup.
   */
  interface Props {
    checked: boolean;
    /** Announced to screen readers; the drawn box carries no text of its own. */
    label: string;
    onToggle: () => void;
  }
  const { checked, label, onToggle }: Props = $props();
</script>

<button
  type="button"
  class="checkbox"
  role="checkbox"
  aria-checked={checked}
  aria-label={label}
  onclick={(e) => { e.stopPropagation(); onToggle(); }}
>
  {#if checked}
    <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect width="16" height="16" rx="3" fill="var(--accent)" />
      <path
        d="M3.5 8L6.5 11L12.5 5"
        stroke="var(--accent-on)"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  {:else}
    <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x="0.5" y="0.5" width="15" height="15" rx="2.5" stroke="var(--border-strong)" />
    </svg>
  {/if}
</button>

<style>
  .checkbox {
    position: relative;
    flex-shrink: 0;
    width: 1.25rem;
    height: 1.25rem;
    padding: 0;
    background: none;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    color: inherit;
    touch-action: manipulation;
  }

  .checkbox svg {
    width: 1rem;
    height: 1rem;
  }

  /* The box is drawn at 20px because that is the right size in a dense list,
     but 20px is half a fingertip. This grows the *hit* area to the height of
     the row without moving anything: vertically it fills the row, and
     horizontally it stops inside the gap so it never steals a tap aimed at the
     item's text, which opens the editor instead. */
  .checkbox::after {
    content: '';
    position: absolute;
    inset: -12px -4px;
  }

  @media print {
    .checkbox {
      pointer-events: none;
    }
  }
</style>
