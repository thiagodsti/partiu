<script lang="ts">
  interface Props {
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    onConfirm: () => void;
    onCancel: () => void;
    danger?: boolean;
  }

  const {
    message,
    confirmLabel = 'Confirm',
    cancelLabel = 'Cancel',
    onConfirm,
    onCancel,
    danger = false,
  }: Props = $props();
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div class="confirm-modal-backdrop" role="presentation" onclick={onCancel}>
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="confirm-modal"
    role="dialog"
    aria-modal="true"
    tabindex="-1"
    onclick={(e) => e.stopPropagation()}
  >
    <p class="confirm-modal-message">{message}</p>
    <div class="confirm-modal-actions">
      <button class="btn btn-secondary" onclick={onCancel}>{cancelLabel}</button>
      <button class={danger ? 'btn btn-danger' : 'btn btn-primary'} onclick={onConfirm}>
        {confirmLabel}
      </button>
    </div>
  </div>
</div>

<style>
  .confirm-modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .confirm-modal {
    background: var(--card-bg, #fff);
    border-radius: var(--radius-md, 8px);
    padding: var(--space-lg, 1.5rem);
    max-width: 360px;
    width: 90%;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  }

  .confirm-modal-message {
    margin: 0 0 var(--space-md, 1rem);
    color: var(--text, #111);
    line-height: 1.5;
  }

  .confirm-modal-actions {
    display: flex;
    gap: var(--space-sm, 0.5rem);
    justify-content: flex-end;
  }
</style>
