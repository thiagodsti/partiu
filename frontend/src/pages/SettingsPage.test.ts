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
  mockGuestsList, mockGuestsCreate, mockGuestsUpdate, mockGuestsDelete,
  MockApiError,
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
  mockGuestsList: vi.fn(),
  mockGuestsCreate: vi.fn(),
  mockGuestsUpdate: vi.fn(),
  mockGuestsDelete: vi.fn(),
  MockApiError: class ApiError extends Error {
    code?: string;
    params?: Record<string, unknown>;
    constructor(message: string, code?: string, params?: Record<string, unknown>) {
      super(message);
      this.code = code;
      this.params = params;
    }
  },
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
  integrationsApi: {
    list: vi.fn().mockResolvedValue([
      { key: 'carto', configured: false, state: 'unset', env_var: 'CARTO_API_KEY' },
      { key: 'photon', configured: true, state: 'public_instance', env_var: 'PHOTON_URL' },
      { key: 'push', configured: true, state: 'set', env_var: null },
    ]),
  },
  sharesApi: {
    listTrustedUsers: vi.fn().mockResolvedValue([]),
    addTrustedUser: vi.fn(),
    removeTrustedUser: vi.fn(),
  },
  guestsApi: {
    list: mockGuestsList,
    create: mockGuestsCreate,
    update: mockGuestsUpdate,
    delete: mockGuestsDelete,
  },
  ApiError: MockApiError,
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
    mockGuestsList.mockResolvedValue([]);
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

  describe('Guests', () => {
    it('renders existing guests', async () => {
      mockGuestsList.mockResolvedValue([{ id: 1, name: 'Grandma', created_at: '2026-01-01T00:00:00Z' }]);
      const { container } = render(SettingsPage);
      await waitFor(() => expect(container.textContent).toContain('Grandma'));
    });

    it('shows empty state when there are no guests', async () => {
      const { container } = render(SettingsPage);
      await waitFor(() => expect(container.textContent).toContain('settings.no_guests_yet'));
    });

    it('adds a guest and shows it in the list', async () => {
      mockGuestsCreate.mockResolvedValue({ id: 2, ok: true, created: true, name: 'Grandpa' });
      const { container, getByPlaceholderText, getByText } = render(SettingsPage);
      await waitFor(() => expect(container.textContent).toContain('settings.no_guests_yet'));

      const input = getByPlaceholderText('settings.guest_name_placeholder') as HTMLInputElement;
      await fireEvent.input(input, { target: { value: 'Grandpa' } });
      await fireEvent.click(getByText('settings.add_guest'));

      await waitFor(() => expect(mockGuestsCreate).toHaveBeenCalledWith('Grandpa'));
      await waitFor(() => expect(container.textContent).toContain('Grandpa'));
    });

    it('renames a guest', async () => {
      mockGuestsList.mockResolvedValue([{ id: 1, name: 'Grandma', created_at: '2026-01-01T00:00:00Z' }]);
      mockGuestsUpdate.mockResolvedValue({ id: 1, name: 'Grandpa', created_at: '2026-01-01T00:00:00Z' });
      const { container, getByText, getByDisplayValue } = render(SettingsPage);
      await waitFor(() => expect(container.textContent).toContain('Grandma'));

      await fireEvent.click(getByText('settings.edit_guest'));
      const editInput = getByDisplayValue('Grandma') as HTMLInputElement;
      await fireEvent.input(editInput, { target: { value: 'Grandpa' } });
      await fireEvent.click(getByText('settings.save_guest'));

      await waitFor(() => expect(mockGuestsUpdate).toHaveBeenCalledWith(1, 'Grandpa'));
      await waitFor(() => expect(container.textContent).toContain('Grandpa'));
    });

    it('deletes a guest', async () => {
      mockGuestsList.mockResolvedValue([{ id: 1, name: 'Grandma', created_at: '2026-01-01T00:00:00Z' }]);
      mockGuestsDelete.mockResolvedValue(null);
      const { container, getByText } = render(SettingsPage);
      await waitFor(() => expect(container.textContent).toContain('Grandma'));

      await fireEvent.click(getByText('settings.delete_guest'));

      await waitFor(() => expect(mockGuestsDelete).toHaveBeenCalledWith(1, false));
      await waitFor(() => expect(container.textContent).not.toContain('Grandma'));
    });

    it('reuses the existing guest instead of listing the same person twice', async () => {
      // The server dedupes on a folded name, so this 201 is a *reuse*. Appending
      // it anyway would repeat the row — and a duplicate key is a hard error in
      // Svelte, which takes the page down rather than showing two rows.
      mockGuestsList.mockResolvedValue([{ id: 1, name: 'Grandma', created_at: '2026-01-01T00:00:00Z' }]);
      mockGuestsCreate.mockResolvedValue({ id: 1, ok: true, created: false, name: 'Grandma' });
      const { container, getByPlaceholderText, getByText } = render(SettingsPage);
      await waitFor(() => expect(container.textContent).toContain('Grandma'));

      const input = getByPlaceholderText('settings.guest_name_placeholder') as HTMLInputElement;
      await fireEvent.input(input, { target: { value: 'grandma' } });
      await fireEvent.click(getByText('settings.add_guest'));

      await waitFor(() => expect(container.textContent).toContain('settings.guest_already_exists'));
      expect(container.textContent?.match(/Grandma/g)?.length).toBe(1);
    });

    it('names the trips a guest is on before deleting them, then deletes on confirmation', async () => {
      // Deleting the address-book entry cascades their roster rows away, taking
      // them off trips this page never shows. Allowed — but not silently.
      mockGuestsList.mockResolvedValue([{ id: 1, name: 'Grandma', created_at: '2026-01-01T00:00:00Z' }]);
      mockGuestsDelete.mockRejectedValueOnce(
        new MockApiError('on trips', 'guest_on_trips', { name: 'Grandma', count: 1, trips: 'Lisbon' })
      );
      const { container, getByText } = render(SettingsPage);
      await waitFor(() => expect(container.textContent).toContain('Grandma'));

      await fireEvent.click(getByText('settings.delete_guest'));
      await waitFor(() => expect(container.textContent).toContain('settings.guest_on_trips_error'));
      expect(container.textContent).toContain('Grandma');

      mockGuestsDelete.mockResolvedValue(null);
      await fireEvent.click(getByText('settings.guest_delete_anyway'));
      await waitFor(() => expect(mockGuestsDelete).toHaveBeenCalledWith(1, true));
      await waitFor(() => expect(container.textContent).not.toContain('Grandma'));
    });

    it('shows a translated error message when delete fails because the guest is in use', async () => {
      mockGuestsList.mockResolvedValue([{ id: 1, name: 'Grandma', created_at: '2026-01-01T00:00:00Z' }]);
      mockGuestsDelete.mockRejectedValue(
        new MockApiError('Guest Grandma is used in 3 existing expense(s)', 'guest_in_use', { name: 'Grandma', count: 3 })
      );
      const { container, getByText } = render(SettingsPage);
      await waitFor(() => expect(container.textContent).toContain('Grandma'));

      await fireEvent.click(getByText('settings.delete_guest'));

      await waitFor(() => expect(container.textContent).toContain('settings.guest_in_use_error'));
    });

    it('falls back to the raw error message for errors without a known code', async () => {
      mockGuestsList.mockResolvedValue([{ id: 1, name: 'Grandma', created_at: '2026-01-01T00:00:00Z' }]);
      mockGuestsDelete.mockRejectedValue(new Error('Guest not found'));
      const { container, getByText } = render(SettingsPage);
      await waitFor(() => expect(container.textContent).toContain('Grandma'));

      await fireEvent.click(getByText('settings.delete_guest'));

      await waitFor(() => expect(container.textContent).toContain('Guest not found'));
    });
  });
});

describe('SettingsPage optional integrations', () => {
  it('lists each integration with its state for an admin', async () => {
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.textContent).toContain('settings.integrations'));
    expect(container.textContent).toContain('integrations.carto');
    expect(container.textContent).toContain('integrations.state_unset');
  });

  it('names the env var only for something that is not configured', async () => {
    // An admin who has already set a key does not need to be told which
    // variable it came from; one who has not does.
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.textContent).toContain('CARTO_API_KEY'));
    expect(container.textContent).not.toContain('PHOTON_URL');
  });

  it('distinguishes Photon on the public instance from a configured key', async () => {
    // A plain configured/not answer would claim credit for a default the admin
    // never chose, so the public instance gets its own state and tone.
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.textContent).toContain('integrations.state_public_instance'));
    expect(container.querySelector('.integration-dot.warn')).toBeTruthy();
  });

  it('marks an unconfigured integration neutrally, not as an error', async () => {
    // These are optional by design: an unset key is a choice, not a fault.
    const { container } = render(SettingsPage);
    await waitFor(() => expect(container.textContent).toContain('settings.integrations'));
    const dots = container.querySelectorAll('.integration-dot');
    expect(dots.length).toBe(3);
    // The unset CARTO row carries neither the ok nor the warn modifier.
    expect(container.querySelectorAll('.integration-dot.ok').length).toBe(1);
  });
});
