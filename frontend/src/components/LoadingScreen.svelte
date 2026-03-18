<script lang="ts">
  interface Props {
    icon?: string;
    message?: string;
  }
  const { icon = '✈', message = 'Loading...' }: Props = $props();
</script>

<div class="loading-screen">
  <div class="loading-icon">{icon}</div>
  <p>{message}</p>
</div>
