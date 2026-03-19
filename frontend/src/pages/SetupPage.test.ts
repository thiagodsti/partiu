import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import SetupPage from './SetupPage.svelte';

const { mockSetup, mockSetCurrentUser } = vi.hoisted(() => ({
  mockSetup: vi.fn(),
  mockSetCurrentUser: vi.fn(),
}));

vi.mock('../api/client', () => ({
  authApi: { setup: mockSetup },
}));

vi.mock('../lib/authStore', () => ({
  currentUser: { set: mockSetCurrentUser, subscribe: (fn: (v: null) => void) => { fn(null); return () => {}; } },
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

async function fillForm(container: HTMLElement, opts: {
  username?: string; password?: string; confirm?: string;
} = {}) {
  const { username = 'admin', password = 'password123', confirm = 'password123' } = opts;
  await fireEvent.input(container.querySelector('#setup-username')!, { target: { value: username } });
  await fireEvent.input(container.querySelector('#setup-password')!, { target: { value: password } });
  await fireEvent.input(container.querySelector('#setup-confirm')!, { target: { value: confirm } });
}

describe('SetupPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the setup form', () => {
    const { container } = render(SetupPage);
    expect(container.querySelector('#setup-username')).toBeInTheDocument();
    expect(container.querySelector('#setup-password')).toBeInTheDocument();
    expect(container.querySelector('#setup-confirm')).toBeInTheDocument();
  });

  it('shows error when passwords do not match', async () => {
    const { container } = render(SetupPage);
    await fillForm(container, { password: 'password123', confirm: 'different' });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(container.textContent).toContain('setup.err_mismatch'));
    expect(mockSetup).not.toHaveBeenCalled();
  });

  it('shows error when password is too short', async () => {
    const { container } = render(SetupPage);
    await fillForm(container, { password: 'short', confirm: 'short' });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(container.textContent).toContain('setup.err_short'));
    expect(mockSetup).not.toHaveBeenCalled();
  });

  it('calls authApi.setup with correct values', async () => {
    mockSetup.mockResolvedValue({ id: '1', username: 'admin', is_admin: true });
    const { container } = render(SetupPage);
    await fillForm(container);
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() =>
      expect(mockSetup).toHaveBeenCalledWith(
        expect.objectContaining({ username: 'admin', password: 'password123' }),
      ),
    );
  });

  it('sets currentUser on successful setup', async () => {
    const user = { id: '1', username: 'admin', is_admin: true };
    mockSetup.mockResolvedValue(user);
    const { container } = render(SetupPage);
    await fillForm(container);
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(mockSetCurrentUser).toHaveBeenCalledWith(user));
  });

  it('shows error message on API failure', async () => {
    mockSetup.mockRejectedValue(new Error('Username taken'));
    const { container } = render(SetupPage);
    await fillForm(container);
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(container.textContent).toContain('Username taken'));
  });
});
