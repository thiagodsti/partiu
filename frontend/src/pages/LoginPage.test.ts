import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import LoginPage from './LoginPage.svelte';

const { mockLogin, mockVerify2fa, mockSetCurrentUser } = vi.hoisted(() => ({
  mockLogin: vi.fn(),
  mockVerify2fa: vi.fn(),
  mockSetCurrentUser: vi.fn(),
}));

vi.mock('../api/client', () => ({
  authApi: { login: mockLogin, verify2fa: mockVerify2fa },
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

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the login form', () => {
    const { container } = render(LoginPage);
    expect(container.querySelector('#login-username')).toBeInTheDocument();
    expect(container.querySelector('#login-password')).toBeInTheDocument();
    expect(container.querySelector('button[type="submit"]')).toBeInTheDocument();
  });

  it('calls authApi.login with credentials on submit', async () => {
    mockLogin.mockResolvedValue({ id: '1', username: 'admin', is_admin: true });
    const { container } = render(LoginPage);

    await fireEvent.input(container.querySelector('#login-username')!, { target: { value: 'admin' } });
    await fireEvent.input(container.querySelector('#login-password')!, { target: { value: 'secret' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(mockLogin).toHaveBeenCalledWith({ username: 'admin', password: 'secret' }));
  });

  it('sets currentUser and redirects on successful login', async () => {
    const user = { id: '1', username: 'admin', is_admin: true };
    mockLogin.mockResolvedValue(user);
    const { container } = render(LoginPage);

    await fireEvent.input(container.querySelector('#login-username')!, { target: { value: 'admin' } });
    await fireEvent.input(container.querySelector('#login-password')!, { target: { value: 'secret' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(mockSetCurrentUser).toHaveBeenCalledWith(user));
  });

  it('shows error message on failed login', async () => {
    mockLogin.mockRejectedValue(new Error('Invalid credentials'));
    const { container } = render(LoginPage);

    await fireEvent.input(container.querySelector('#login-username')!, { target: { value: 'admin' } });
    await fireEvent.input(container.querySelector('#login-password')!, { target: { value: 'wrong' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(container.querySelector('.auth-error')).toBeInTheDocument());
    expect(container.querySelector('.auth-error')!.textContent).toContain('Invalid credentials');
  });

  it('switches to TOTP step when requires_2fa is returned', async () => {
    mockLogin.mockResolvedValue({ requires_2fa: true });
    const { container } = render(LoginPage);

    await fireEvent.input(container.querySelector('#login-username')!, { target: { value: 'admin' } });
    await fireEvent.input(container.querySelector('#login-password')!, { target: { value: 'secret' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(container.querySelector('#totp-code')).toBeInTheDocument());
  });

  it('calls authApi.verify2fa when 6-digit TOTP code is entered', async () => {
    mockLogin.mockResolvedValue({ requires_2fa: true });
    mockVerify2fa.mockResolvedValue({ id: '1', username: 'admin', is_admin: true });
    const { container } = render(LoginPage);

    await fireEvent.input(container.querySelector('#login-username')!, { target: { value: 'admin' } });
    await fireEvent.input(container.querySelector('#login-password')!, { target: { value: 'secret' } });
    await fireEvent.submit(container.querySelector('form')!);
    await waitFor(() => expect(container.querySelector('#totp-code')).toBeInTheDocument());

    await fireEvent.input(container.querySelector('#totp-code')!, { target: { value: '123456' } });

    await waitFor(() => expect(mockVerify2fa).toHaveBeenCalledWith('123456'));
  });

  it('shows TOTP error on failed verification', async () => {
    mockLogin.mockResolvedValue({ requires_2fa: true });
    mockVerify2fa.mockRejectedValue(new Error('Invalid code'));
    const { container } = render(LoginPage);

    await fireEvent.input(container.querySelector('#login-username')!, { target: { value: 'admin' } });
    await fireEvent.input(container.querySelector('#login-password')!, { target: { value: 'secret' } });
    await fireEvent.submit(container.querySelector('form')!);
    await waitFor(() => expect(container.querySelector('#totp-code')).toBeInTheDocument());

    await fireEvent.input(container.querySelector('#totp-code')!, { target: { value: '000000' } });

    await waitFor(() => expect(container.querySelector('.auth-error')).toBeInTheDocument());
  });
});
