import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import TripCard from './TripCard.svelte';
import type { Trip } from '../api/types';

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string, opts?: unknown) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

const badgeSnippet = createRawSnippet(() => ({
  render: () => '<span class="test-badge">Upcoming</span>',
}));

const footerSnippet = createRawSnippet(() => ({
  render: () => '<button class="test-footer-btn">Open Album</button>',
}));

function makeTrip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: 'trip-1',
    name: 'Paris Adventure',
    start_date: '2025-06-01',
    end_date: '2025-06-10',
    origin_airport: 'GRU',
    destination_airport: 'CDG',
    booking_refs: ['ABC123'],
    flight_count: 2,
    ...overrides,
  };
}

const defaultProps = {
  trip: makeTrip(),
  href: '#/trips/trip-1',
  imageUrl: '/api/trips/trip-1/image',
  imgFailed: false,
  refreshing: false,
  onImageError: vi.fn(),
  onRefreshImage: vi.fn(),
  badge: badgeSnippet,
};

describe('TripCard', () => {
  it('renders the trip name', () => {
    const { getByText } = render(TripCard, { props: defaultProps });
    expect(getByText('Paris Adventure')).toBeInTheDocument();
  });

  it('link wraps the card with the correct href', () => {
    const { container } = render(TripCard, { props: defaultProps });
    const link = container.querySelector('a.card-link') as HTMLAnchorElement;
    expect(link).toBeInTheDocument();
    expect(link.getAttribute('href')).toBe('#/trips/trip-1');
  });

  it('renders the cover image when not failed', () => {
    const { container } = render(TripCard, { props: defaultProps });
    const img = container.querySelector('.trip-card-cover-img') as HTMLImageElement;
    expect(img).toBeInTheDocument();
    expect(img.getAttribute('src')).toBe('/api/trips/trip-1/image');
  });

  it('shows fallback icon when imgFailed is true', () => {
    const { container } = render(TripCard, {
      props: { ...defaultProps, imgFailed: true },
    });
    expect(container.querySelector('.trip-card-no-image-icon')).toBeInTheDocument();
    expect(container.querySelector('.trip-card-cover-img')).toBeNull();
  });

  it('refresh button is enabled when not refreshing', () => {
    const { container } = render(TripCard, { props: defaultProps });
    const btn = container.querySelector('.trip-card-img-refresh') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toBe('↻');
  });

  it('refresh button is disabled and shows spinner when refreshing', () => {
    const { container } = render(TripCard, {
      props: { ...defaultProps, refreshing: true },
    });
    const btn = container.querySelector('.trip-card-img-refresh') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toBe('…');
  });

  it('calls onRefreshImage when refresh button is clicked', async () => {
    const onRefreshImage = vi.fn();
    const { container } = render(TripCard, {
      props: { ...defaultProps, onRefreshImage },
    });
    await fireEvent.click(container.querySelector('.trip-card-img-refresh')!);
    expect(onRefreshImage).toHaveBeenCalledOnce();
  });

  it('calls onImageError when image fails to load', async () => {
    const onImageError = vi.fn();
    const { container } = render(TripCard, {
      props: { ...defaultProps, onImageError },
    });
    await fireEvent.error(container.querySelector('.trip-card-cover-img')!);
    expect(onImageError).toHaveBeenCalledOnce();
  });

  it('renders the badge snippet', () => {
    const { container } = render(TripCard, { props: defaultProps });
    expect(container.querySelector('.test-badge')).toBeInTheDocument();
    expect(container.querySelector('.test-badge')!.textContent).toBe('Upcoming');
  });

  it('renders the footer snippet when provided', () => {
    const { container } = render(TripCard, {
      props: { ...defaultProps, footer: footerSnippet },
    });
    expect(container.querySelector('.test-footer-btn')).toBeInTheDocument();
  });

  it('does not render footer snippet when not provided', () => {
    const { container } = render(TripCard, { props: defaultProps });
    expect(container.querySelector('.test-footer-btn')).toBeNull();
  });

  it('renders booking refs span when refs are present', () => {
    const { container } = render(TripCard, { props: defaultProps });
    // t() mock returns the key — the span is rendered with class text-muted
    const refSpan = container.querySelector('.trip-card-footer .text-muted');
    expect(refSpan).toBeInTheDocument();
  });

  it('does not render booking refs section when empty', () => {
    const { container } = render(TripCard, {
      props: { ...defaultProps, trip: makeTrip({ booking_refs: [] }) },
    });
    const footer = container.querySelector('.trip-card-footer');
    // footer div is always rendered but muted text span should be absent
    expect(footer!.querySelector('.text-muted')).toBeNull();
  });

  it('renders date meta when dates are present', () => {
    const { container } = render(TripCard, { props: defaultProps });
    expect(container.querySelector('.trip-card-meta')).toBeInTheDocument();
  });

  it('does not render date meta when start_date is null', () => {
    const { container } = render(TripCard, {
      props: { ...defaultProps, trip: makeTrip({ start_date: null, end_date: null }) },
    });
    expect(container.querySelector('.trip-card-meta')).toBeNull();
  });
});
