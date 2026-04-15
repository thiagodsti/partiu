import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import SettingsPage from './SettingsPage.svelte';

const {
  mockSettingsGet, mockSettingsUpdate, mockSettingsTestImap,
  mockSyncStatus, mockSyncNow,
  mockNotifVapidStatus, mockNotifGetPrefs,
  mockAirportCount, mockReloadAirports,
  mockAuthChangePassword,
} = vi.hoisted(() => ({
  mockSettingsGet: vi.fn(),
  mockSettingsUpdate: vi.fn(),
  mockSettingsTestImap: vi.fn(),
  mockSyncStatus: vi.fn(),
  mockSyncNow: vi.fn(),
  mockNotifVapidStatus: vi.fn(),
  mockNotifGetPrefs: vi.fn(),
  mockAirportCount: vi.fn(),
  mockReloadAirports: vi.fn(),
  mockAuthChangePassword: vi.fn(),
}));

vi.mock('../api/client', () => ({
  settingsApi: {
    get: mockSettingsGet,
    update: mockSettingsUpdate,
    testImap: mockSettingsTestImap,
    airportCount: mockAirportCount,
    reloadAirports: mockReloadAirports,
    testImmich: vi.fn(),
  },
  syncApi: { status: mockSyncStatus, now: mockSyncNow, cacheInfo: vi.fn().mockResolvedValue({ exists: false, count: 0, oldest: null, newest: null }), fromCache: vi.fn() },
  authApi: { changePassword: mockAuthChangePassword },
  notificationsApi: {
    vapidStatus: mockNotifVapidStatus,
    getPreferences: mockNotifGetPrefs,
    updatePreferences: vi.fn(),
    testPush: vi.fn(),
    vapidPublicKey: vi.fn(),
  },
  versionApi: {
    get: vi.fn().mockResolvedValue({ current_version: '2.2.5', latest_version: null, update_available: false }),
  },
}));

vi.mock('../lib/authStore', () => ({
  currentUser: writable({ id: '1', username: 'admin', is_admin: true, totp_enabled: false }),
}));

vi.mock('../lib/themeStore', () => ({
  theme: writable('system'),
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
  locale: writable('en'),
  setLocale: vi.fn(),
  LOCALES: [{ code: 'en', label: 'English' }, { code: 'pt-BR', label: 'Português' }],
}));

vi.mock('svelte-i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

vi.mock('qrcode', () => ({ toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,abc') }));

vi.mock('../lib/notifications', () => ({
  isSupported: vi.fn().mockReturnValue(false),
  getStatus: vi.fn().mockResolvedValue('unsupported'),
  subscribe: vi.fn(),
  unsubscribe: vi.fn(),
}));

const SETTINGS = {
  gmail_address: 'test@gmail.com',
  gmail_app_password_set: true,
  sync_interval_minutes: 10,
  first_sync_days: 30,
  imap_host: 'imap.gmail.com',
  imap_port: 993,
  smtp_server_enabled: false,
  smtp_domain: '',
  smtp_server_port: 2525,
  smtp_recipient_address: '',
  smtp_allowed_senders: '',
  immich_url: '',
  immich_api_key_set: false,
};

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSettingsGet.mockResolvedValue(SETTINGS);
    mockSyncStatus.mockResolvedValue({ status: 'idle', last_synced_at: null, last_error: null, sync_interval_minutes: 10 });
    mockNotifVapidStatus.mockResolvedValue({ configured: true, source: 'auto' });
    mockNotifGetPrefs.mockResolvedValue({ flight_reminder: true, checkin_reminder: true, trip_reminder: true, delay_alert: true });
    mockAirportCount.mockResolvedValue({ count: 5000 });
  });

  it('shows loading screen initially', () => {
    mockSettingsGet.mockReturnValue(new Promise(() => {}));
    const { container } = render(SettingsPage);
    expect(container.querySelector('.loading-screen')).toBeInTheDocument();
  });

  it('shows error state when load fails', async () => {
    mockSettingsGet.mockRejectedValue(new Error('Forbidden'));
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.textContent).toContain('Forbidden'));
  });

  it('renders email account section with current address', async () => {
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.querySelector('.loading-screen')).not.toBeInTheDocument());
    expect(container.querySelector<HTMLInputElement>('#gmail-address')?.value).toBe('test@gmail.com');
  });

  it('renders airport count', async () => {
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.textContent).toContain('settings.airports_loaded'));
  });

  it('renders notifications section', async () => {
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.textContent).toContain('settings.notif_title'));
  });

  it('renders appearance section', async () => {
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.textContent).toContain('settings.appearance'));
  });

  it('calls settingsApi.update when form is submitted', async () => {
    mockSettingsUpdate.mockResolvedValue({});
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.querySelector('.loading-screen')).not.toBeInTheDocument());

    const form = container.querySelector<HTMLFormElement>('#gmail-address')?.closest('form');
    expect(form).toBeInTheDocument();
    await fireEvent.submit(form!);

    await waitFor(() => expect(mockSettingsUpdate).toHaveBeenCalled());
  });

  it('shows admin-only Push Notifications section for admin user', async () => {
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.textContent).toContain('settings.push_title'));
  });
});
