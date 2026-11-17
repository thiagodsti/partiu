import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const { mockList, mockCreate, mockRevoke } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockCreate: vi.fn(),
  mockRevoke: vi.fn(),
}));

vi.mock('../api/client', () => ({
  apiKeysApi: { list: mockList, create: mockCreate, revoke: mockRevoke },
}));

vi.mock('../lib/i18n', async () => {
  const { readable } = await import('svelte/store');
  return {
    t: readable((key: string, opts?: { values?: Record<string, unknown> }) => {
      const v = opts?.values ?? {};
      return Object.keys(v).length ? `${key}:${Object.values(v).join(',')}` : key;
    }),
  };
});

import ApiKeysPanel from './ApiKeysPanel.svelte';

const listed = {
  id: 1,
  name: 'Home Assistant',
  prefix: 'partiu_AbCdEf',
  scope: 'read' as const,
  created_at: '2026-11-01T10:00:00+00:00',
  last_used_at: null,
  expires_at: null,
};

/** Selects the option and fires the change event the panel listens for. */
async function choose(select: HTMLSelectElement, value: string) {
  for (const opt of Array.from(select.options)) opt.selected = opt.value === value;
  await fireEvent.change(select);
}

describe('ApiKeysPanel', () => {
  beforeEach(() => {
    mockList.mockReset();
    mockCreate.mockReset();
    mockRevoke.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('starts empty: nothing is created until someone asks', async () => {
    mockList.mockResolvedValue([]);
    render(ApiKeysPanel);
    await waitFor(() => expect(screen.getByText('api_keys.empty')).toBeTruthy());
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('lists a key by name and prefix, never by value', async () => {
    mockList.mockResolvedValue([listed]);
    render(ApiKeysPanel);
    await waitFor(() => expect(screen.getByText('Home Assistant')).toBeTruthy());
    expect(screen.getByText('partiu_AbCdEf…')).toBeTruthy();
    expect(screen.getByText(/api_keys\.never_used/)).toBeTruthy();
  });

  it('creating shows the secret once, with the chosen scope and expiry', async () => {
    mockList.mockResolvedValue([]);
    mockCreate.mockResolvedValue({ ...listed, id: 2, name: 'CI', scope: 'write', key: 'partiu_secret-value' });
    render(ApiKeysPanel);
    await waitFor(() => screen.getByText('api_keys.empty'));

    await fireEvent.input(screen.getByLabelText('api_keys.name'), { target: { value: ' CI ' } });
    await choose(screen.getByLabelText('api_keys.scope') as HTMLSelectElement, 'write');
    await choose(screen.getByLabelText('api_keys.expires') as HTMLSelectElement, '');
    await fireEvent.click(screen.getByText('api_keys.create'));

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({ name: 'CI', scope: 'write', expires_in_days: null }),
    );
    const secret = (await screen.findByLabelText('api_keys.secret_label')) as HTMLInputElement;
    expect(secret.value).toBe('partiu_secret-value');
    expect(screen.getByText('CI')).toBeTruthy();

    await fireEvent.click(screen.getByText('api_keys.done'));
    expect(screen.queryByLabelText('api_keys.secret_label')).toBeNull();
    expect(document.body.textContent).not.toContain('partiu_secret-value');
  });

  it('revoke asks first, then removes the row', async () => {
    mockList.mockResolvedValue([listed]);
    mockRevoke.mockResolvedValue(null);
    const confirmMock = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
    vi.stubGlobal('confirm', confirmMock);
    render(ApiKeysPanel);
    await waitFor(() => screen.getByText('Home Assistant'));

    await fireEvent.click(screen.getByText('api_keys.revoke'));
    expect(mockRevoke).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByText('api_keys.revoke'));
    await waitFor(() => expect(mockRevoke).toHaveBeenCalledWith(1));
    await waitFor(() => expect(screen.queryByText('Home Assistant')).toBeNull());
  });

  it('hides the create form on a demo', async () => {
    mockList.mockResolvedValue([]);
    render(ApiKeysPanel, { props: { demo: true } });
    await waitFor(() => screen.getByText('api_keys.empty'));
    expect(screen.getByText('demo.locked_api_keys')).toBeTruthy();
    expect(screen.queryByText('api_keys.create')).toBeNull();
  });

  it('reports a failed create without losing the form', async () => {
    mockList.mockResolvedValue([]);
    mockCreate.mockRejectedValue(new Error('You can hold at most 20 API keys'));
    render(ApiKeysPanel);
    await waitFor(() => screen.getByText('api_keys.empty'));
    await fireEvent.input(screen.getByLabelText('api_keys.name'), { target: { value: 'x' } });
    await fireEvent.click(screen.getByText('api_keys.create'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('at most 20'));
    expect((screen.getByLabelText('api_keys.name') as HTMLInputElement).value).toBe('x');
  });
});
