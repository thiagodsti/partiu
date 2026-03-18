<script lang="ts">
  import { t } from "svelte-i18n";

  interface Props {
    icon?: string;
    message?: string;
  }
  const { icon = "✈" }: Props = $props();
</script>

<div class="loading-screen">
  <div class="loading-icon">{icon}</div>
  <p>{$t("loading")}}...</p>
</div>
