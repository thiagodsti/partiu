import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import ImmichAlbumButton from './ImmichAlbumButton.svelte';

const { mockCreateImmichAlbum } = vi.hoisted(() => ({
  mockCreateImmichAlbum: vi.fn(),
}));

vi.mock('../api/client', () => ({
  tripsApi: { createImmichAlbum: mockCreateImmichAlbum },
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

const BASE_PROPS = {
  tripId: 'trip-1',
  immichAlbumId: null as string | null | undefined,
  immichBaseUrl: 'https://immich.example.com',
};

describe('ImmichAlbumButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.stubGlobal('open', vi.fn());
    vi.stubGlobal('location', { href: '' });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('shows create label when no album exists', () => {
    const { getByText } = render(ImmichAlbumButton, { props: BASE_PROPS });
    expect(getByText('immich.create_album')).toBeInTheDocument();
  });

  it('shows open label when album already exists', () => {
    const { getByText } = render(ImmichAlbumButton, {
      props: { ...BASE_PROPS, immichAlbumId: 'album-abc' },
    });
    expect(getByText('immich.open_album')).toBeInTheDocument();
  });

  it('tries Immich deep link when opening existing album', async () => {
    const { getByText } = render(ImmichAlbumButton, {
      props: { ...BASE_PROPS, immichAlbumId: 'album-xyz' },
    });

    await fireEvent.click(getByText('immich.open_album'));

    expect(window.location.href).toBe('immich:///albums/album-xyz');
    expect(mockCreateImmichAlbum).not.toHaveBeenCalled();
  });

  it('falls back to browser when app is not installed (timer fires)', async () => {
    const { getByText } = render(ImmichAlbumButton, {
      props: { ...BASE_PROPS, immichAlbumId: 'album-xyz' },
    });

    await fireEvent.click(getByText('immich.open_album'));
    vi.advanceTimersByTime(1500);

    expect(window.open).toHaveBeenCalledWith(
      'https://immich.example.com/albums/album-xyz',
      '_blank',
      'noopener',
    );
    expect(mockCreateImmichAlbum).not.toHaveBeenCalled();
  });

  it('does not open browser when app opens (visibilitychange fires)', async () => {
    const { getByText } = render(ImmichAlbumButton, {
      props: { ...BASE_PROPS, immichAlbumId: 'album-xyz' },
    });

    await fireEvent.click(getByText('immich.open_album'));

    // Simulate app opening: page becomes hidden
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    Object.defineProperty(document, 'hidden', { value: false, configurable: true });

    vi.advanceTimersByTime(2000);

    expect(window.open).not.toHaveBeenCalled();
  });

  it('calls tripsApi.createImmichAlbum when no album exists', async () => {
    mockCreateImmichAlbum.mockResolvedValue({ album_id: 'new-id', album_url: null });
    const { getByText } = render(ImmichAlbumButton, { props: BASE_PROPS });

    await fireEvent.click(getByText('immich.create_album'));
    await waitFor(() => expect(mockCreateImmichAlbum).toHaveBeenCalledWith('trip-1'));
  });

  it('shows creating label while API call is in progress', async () => {
    let resolve!: (v: unknown) => void;
    mockCreateImmichAlbum.mockReturnValue(new Promise((r) => { resolve = r; }));
    const { getByText } = render(ImmichAlbumButton, { props: BASE_PROPS });

    await fireEvent.click(getByText('immich.create_album'));
    await waitFor(() => expect(getByText('immich.creating_album')).toBeInTheDocument());

    resolve({ album_id: 'done', album_url: null });
  });

  it('disables button while creating', async () => {
    let resolve!: (v: unknown) => void;
    mockCreateImmichAlbum.mockReturnValue(new Promise((r) => { resolve = r; }));
    const { container, getByText } = render(ImmichAlbumButton, { props: BASE_PROPS });

    await fireEvent.click(getByText('immich.create_album'));
    await waitFor(() => {
      const btn = container.querySelector('button') as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
    });

    resolve({ album_id: 'done', album_url: null });
  });

  it('calls onAlbumCreated callback with new album id', async () => {
    mockCreateImmichAlbum.mockResolvedValue({ album_id: 'created-id', album_url: null });
    const onAlbumCreated = vi.fn();
    const { getByText } = render(ImmichAlbumButton, {
      props: { ...BASE_PROPS, onAlbumCreated },
    });

    await fireEvent.click(getByText('immich.create_album'));
    await waitFor(() => expect(onAlbumCreated).toHaveBeenCalledWith('created-id'));
  });

  it('tries deep link for newly created album', async () => {
    mockCreateImmichAlbum.mockResolvedValue({ album_id: 'new-id', album_url: null });
    const { getByText } = render(ImmichAlbumButton, { props: BASE_PROPS });

    await fireEvent.click(getByText('immich.create_album'));
    await waitFor(() =>
      expect(window.location.href).toBe('immich:///albums/new-id'),
    );
  });

  it('shows error message when API call fails', async () => {
    mockCreateImmichAlbum.mockRejectedValue(new Error('Immich unavailable'));
    const { getByText, findByText } = render(ImmichAlbumButton, { props: BASE_PROPS });

    await fireEvent.click(getByText('immich.create_album'));
    expect(await findByText('Immich unavailable')).toBeInTheDocument();
  });

  it('forwards style prop to the button', () => {
    const { container } = render(ImmichAlbumButton, {
      props: { ...BASE_PROPS, style: 'width:100%' },
    });
    const btn = container.querySelector('button') as HTMLButtonElement;
    expect(btn.getAttribute('style')).toMatch(/width:\s*100%/);
  });
});
