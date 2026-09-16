import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import LoginPage from './LoginPage.svelte';

const { mockLogin, mockVerify2fa, mockSetCurrentUser, mockPublicConfig } = vi.hoisted(() => ({
  mockLogin: vi.fn(),
  mockVerify2fa: vi.fn(),
  mockSetCurrentUser: vi.fn(),
  mockPublicConfig: vi.fn(),
}));

vi.mock('../api/client', () => ({
  authApi: { login: mockLogin, verify2fa: mockVerify2fa, publicConfig: mockPublicConfig },
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
    mockPublicConfig.mockResolvedValue({ demo: false, demo_username: '', demo_password: '' });
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

  /* Signing in does not remount the app, so whatever the login response omits
   * is missing until the next full load — that is how the demo banner came to
   * need a hard refresh. The page must pass the response through whole. */
  it('passes the server config on the login response into the user store', async () => {
    const user = {
      id: '1',
      username: 'demo',
      is_admin: false,
      demo: true,
      announcement: 'Back at 03:00',
      carto_api_key: 'carto-key',
    };
    mockLogin.mockResolvedValue(user);
    const { container } = render(LoginPage);

    await fireEvent.input(container.querySelector('#login-username')!, { target: { value: 'demo' } });
    await fireEvent.input(container.querySelector('#login-password')!, { target: { value: 'demo1234' } });
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

  describe('demo instance notice', () => {
    it('shows nothing on an ordinary install', async () => {
      const { container } = render(LoginPage);
      await waitFor(() => expect(mockPublicConfig).toHaveBeenCalled());
      expect(container.querySelector('.demo-note')).toBeNull();
    });

    it('prints the demo credentials when the server publishes them', async () => {
      mockPublicConfig.mockResolvedValue({
        demo: true,
        demo_username: 'demo',
        demo_password: 'demo1234',
      });
      const { container } = render(LoginPage);

      await waitFor(() => expect(container.querySelector('.demo-note')).toBeInTheDocument());
      const creds = container.querySelectorAll('.demo-creds dd');
      expect(creds[0].textContent).toBe('demo');
      expect(creds[1].textContent).toBe('demo1234');
    });

    it('signs in with those credentials when the button is used', async () => {
      mockPublicConfig.mockResolvedValue({
        demo: true,
        demo_username: 'demo',
        demo_password: 'demo1234',
      });
      mockLogin.mockResolvedValue({ id: '2', username: 'demo', is_admin: false });
      const { container } = render(LoginPage);

      await waitFor(() => expect(container.querySelector('.demo-btn')).toBeInTheDocument());
      await fireEvent.click(container.querySelector('.demo-btn')!);

      await waitFor(() =>
        expect(mockLogin).toHaveBeenCalledWith({ username: 'demo', password: 'demo1234' }),
      );
    });

    // The form is the feature; the notice is decoration. A server too old to
    // know the endpoint must not take the login page down with it.
    it('still renders the form when the config call fails', async () => {
      mockPublicConfig.mockRejectedValue(new Error('404'));
      const { container } = render(LoginPage);

      await waitFor(() => expect(mockPublicConfig).toHaveBeenCalled());
      expect(container.querySelector('#login-username')).toBeInTheDocument();
      expect(container.querySelector('.demo-note')).toBeNull();
    });
  });
});
