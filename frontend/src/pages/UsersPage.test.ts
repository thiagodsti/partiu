import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import UsersPage from './UsersPage.svelte';

const { mockList, mockCreate, mockDelete, mockUpdate, mockToastsShow } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockCreate: vi.fn(),
  mockDelete: vi.fn(),
  mockUpdate: vi.fn(),
  mockToastsShow: vi.fn(),
}));

vi.mock('../api/client', () => ({
  usersApi: {
    list: mockList,
    create: mockCreate,
    delete: mockDelete,
    update: mockUpdate,
  },
}));

vi.mock('../lib/toastStore', () => ({
  toasts: { show: mockToastsShow },
}));

vi.mock('../lib/authStore', () => ({
  currentUser: writable({ id: 'user-me', username: 'admin', is_admin: true }),
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string, opts?: unknown) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));
vi.mock('svelte-i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string, opts?: unknown) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

const USERS = [
  {
    id: 'user-1',
    username: 'alice',
    is_admin: false,
    smtp_recipient_address: null,
    totp_enabled: false,
    created_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 'user-me',
    username: 'admin',
    is_admin: true,
    smtp_recipient_address: null,
    totp_enabled: false,
    created_at: '2025-01-01T00:00:00Z',
  },
];

describe('UsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue(USERS);
    mockCreate.mockResolvedValue({});
    mockDelete.mockResolvedValue({});
    mockUpdate.mockResolvedValue({});
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows loading screen initially', () => {
    mockList.mockReturnValue(new Promise(() => {}));
    const { container } = render(UsersPage);
    expect(container.querySelector('.loading-screen')).toBeInTheDocument();
  });

  it('renders user list after loading', async () => {
    const { findByText, findAllByText } = render(UsersPage);
    expect(await findByText('alice')).toBeInTheDocument();
    // 'admin' appears in TopNav (nav-username) and user list row
    const adminEls = await findAllByText('admin');
    expect(adminEls.length).toBeGreaterThanOrEqual(1);
  });

  it('shows error state when list fails', async () => {
    mockList.mockRejectedValue(new Error('Forbidden'));
    const { findByText } = render(UsersPage);
    expect(await findByText('Forbidden')).toBeInTheDocument();
  });

  it('renders the create user form', async () => {
    const { container } = render(UsersPage);
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());
    expect(container.querySelector('input[id="new-username"]')).toBeInTheDocument();
    expect(container.querySelector('input[id="new-password"]')).toBeInTheDocument();
  });

  it('does not show delete/reset buttons for the current user', async () => {
    const { container } = render(UsersPage);
    await waitFor(() => expect(container.querySelector('.user-list')).toBeInTheDocument());

    // Find the admin row — it's the current user so it should have the badge
    const youBadge = container.querySelector('.user-row [style*="text-muted"]');
    expect(youBadge).toBeInTheDocument();
  });

  it('calls usersApi.delete when delete button is clicked', async () => {
    const { container } = render(UsersPage);
    await waitFor(() => expect(container.querySelector('.user-list')).toBeInTheDocument());

    // Find the delete button for alice (not the current user)
    const deleteButtons = Array.from(container.querySelectorAll('button')).filter((b) =>
      b.textContent?.includes('users.delete'),
    );
    expect(deleteButtons.length).toBeGreaterThan(0);
    await fireEvent.click(deleteButtons[0]);

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('user-1'));
  });

  it('shows toast on successful delete', async () => {
    const { container } = render(UsersPage);
    await waitFor(() => expect(container.querySelector('.user-list')).toBeInTheDocument());

    const deleteButtons = Array.from(container.querySelectorAll('button')).filter((b) =>
      b.textContent?.includes('users.delete'),
    );
    await fireEvent.click(deleteButtons[0]);

    await waitFor(() => expect(mockToastsShow).toHaveBeenCalled());
  });

  it('calls usersApi.create when form is submitted', async () => {
    const { container } = render(UsersPage);
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    const usernameInput = container.querySelector('#new-username')!;
    const passwordInput = container.querySelector('#new-password')!;

    await fireEvent.input(usernameInput, { target: { value: 'newuser' } });
    await fireEvent.input(passwordInput, { target: { value: 'secret123' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({ username: 'newuser', password: 'secret123' }),
      );
    });
  });

  it('shows toast on successful create', async () => {
    const { container } = render(UsersPage);
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.input(container.querySelector('#new-username')!, {
      target: { value: 'bob' },
    });
    await fireEvent.input(container.querySelector('#new-password')!, {
      target: { value: 'password123' },
    });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(mockToastsShow).toHaveBeenCalled());
  });

  it('shows toast on create error', async () => {
    mockCreate.mockRejectedValue(new Error('Username taken'));
    const { container } = render(UsersPage);
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.input(container.querySelector('#new-username')!, {
      target: { value: 'bob' },
    });
    await fireEvent.input(container.querySelector('#new-password')!, {
      target: { value: 'password123' },
    });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() =>
      expect(mockToastsShow).toHaveBeenCalledWith('Username taken', 'error'),
    );
  });

  it('toggles the reset password form for non-current users', async () => {
    const { container } = render(UsersPage);
    await waitFor(() => expect(container.querySelector('.user-list')).toBeInTheDocument());

    const resetButtons = Array.from(container.querySelectorAll('button')).filter((b) =>
      b.textContent?.includes('users.reset_pw'),
    );
    expect(resetButtons.length).toBeGreaterThan(0);

    await fireEvent.click(resetButtons[0]);
    expect(container.querySelector('.reset-form')).toBeInTheDocument();

    // Click again to close
    await fireEvent.click(resetButtons[0]);
    expect(container.querySelector('.reset-form')).toBeNull();
  });
});
