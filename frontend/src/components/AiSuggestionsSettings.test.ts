import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import AiSuggestionsSettings from './AiSuggestionsSettings.svelte';

const { mockStatus, mockSet } = vi.hoisted(() => ({ mockStatus: vi.fn(), mockSet: vi.fn() }));

vi.mock('../api/client', () => ({ suggestionsApi: { status: mockStatus, setUseHistory: mockSet } }));
vi.mock('../lib/toastStore', () => ({ toasts: { show: vi.fn() } }));
vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

describe('AiSuggestionsSettings', () => {
  beforeEach(() => {
    mockStatus.mockReset();
    mockSet.mockReset().mockResolvedValue({ use_history: true });
  });

  it('renders nothing when the server has no AI set up', async () => {
    mockStatus.mockResolvedValue({ available: false, use_history: false, daily_limit: 40, used_today: 0 });
    const { container } = render(AiSuggestionsSettings);
    await waitFor(() => expect(mockStatus).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="ai-suggestions-settings"]')).toBeNull();
  });

  it('is off by default and saves the choice', async () => {
    mockStatus.mockResolvedValue({ available: true, use_history: false, daily_limit: 40, used_today: 3 });
    render(AiSuggestionsSettings);
    const box = (await screen.findByRole('checkbox')) as HTMLInputElement;
    expect(box.checked).toBe(false);
    await fireEvent.click(box);
    expect(mockSet).toHaveBeenCalledWith(true);
  });
});
