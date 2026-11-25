import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

const { count } = vi.hoisted(() => ({ count: vi.fn() }));

vi.mock('../api/client', () => ({ emailReviewApi: { count } }));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string, o?: { values?: Record<string, unknown> }) => string) => void) => {
      fn((k, o) => (o?.values ? `${k}:${JSON.stringify(o.values)}` : k));
      return () => {};
    },
  },
}));

import ReviewEmailsNotice from './ReviewEmailsNotice.svelte';

describe('ReviewEmailsNotice', () => {
  beforeEach(() => count.mockReset());

  it('says nothing when there is nothing to review', async () => {
    count.mockResolvedValue({ count: 0 });
    const { container } = render(ReviewEmailsNotice);
    await Promise.resolve();
    expect(container.querySelector('[data-testid=review-notice]')).toBeNull();
  });

  it('links to the review page with the count', async () => {
    count.mockResolvedValue({ count: 3 });
    const { container } = render(ReviewEmailsNotice);
    await waitFor(() => expect(container.querySelector('[data-testid=review-notice]')).not.toBeNull());
    const link = container.querySelector('a')!;
    expect(link.getAttribute('href')).toBe('#/review-emails');
    expect(link.textContent).toContain('review.notice_many:{"count":3}');
  });

  it('uses the singular for one email', async () => {
    count.mockResolvedValue({ count: 1 });
    const { container } = render(ReviewEmailsNotice);
    await waitFor(() => expect(container.textContent).toContain('review.notice_one'));
  });
});
