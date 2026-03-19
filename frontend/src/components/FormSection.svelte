<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    title?: string;
    children: Snippet;
  }
  const { title, children }: Props = $props();
</script>

<section class="form-section">
  {#if title}<div class="form-section-title">{title}</div>{/if}
  {@render children()}
</section>
