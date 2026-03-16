<script lang="ts">
  interface Props {
    title: string;
    backHref?: string | null;
  }
  const { title, backHref = null }: Props = $props();
</script>

<nav class="top-nav">
  {#if backHref}
    <a class="nav-back" href={backHref}>←</a>
  {/if}
  <span class="nav-title">{title}</span>
</nav>
