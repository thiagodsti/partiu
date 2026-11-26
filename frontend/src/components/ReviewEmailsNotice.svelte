<script lang="ts">
  /* One quiet line on the trips list when the sync left booking emails it
   * could not read (backend/email_review). Deliberately not a banner or a
   * badge: it is something to look at when convenient, not an alarm. */
  import { emailReviewApi } from '../api/client';
  import { t } from '../lib/i18n';

  interface Props {
    /** Bumped by the page after it reloads (a sync may have added emails). */
    refresh?: number;
  }
  const { refresh = 0 }: Props = $props();

  let count = $state(0);
  $effect(() => {
    void refresh;
    emailReviewApi
      .count()
      .then((r) => (count = r.count))
      .catch(() => {});
  });
</script>

{#if count > 0}
  <a class="review-notice" href="#/review-emails" data-testid="review-notice">
    <span class="review-notice-dot" aria-hidden="true"></span>
    <span class="review-notice-text">
      {count === 1 ? $t('review.notice_one') : $t('review.notice_many', { values: { count } })}
    </span>
    <span class="review-notice-action">{$t('review.notice_action')} →</span>
  </a>
{/if}

<style>
  .review-notice {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    margin-bottom: var(--space-md);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--bg-card);
    color: var(--text-primary);
    text-decoration: none;
    font-size: 0.9rem;
  }
  .review-notice:hover {
    border-color: var(--border-strong);
    text-decoration: none;
  }
  .review-notice-dot {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--warning, #f59e0b);
  }
  .review-notice-text {
    flex: 1;
    min-width: 0;
  }
  .review-notice-action {
    flex: none;
    color: var(--accent-text);
    font-weight: 600;
  }
</style>
