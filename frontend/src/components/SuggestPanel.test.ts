import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import SuggestPanel, { forgetSuggestions } from './SuggestPanel.svelte';

const { mockSuggest } = vi.hoisted(() => ({ mockSuggest: vi.fn() }));

vi.mock('../api/client', () => ({ suggestionsApi: { suggest: mockSuggest } }));
vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string, o?: { values?: Record<string, unknown> }) => string) => void) => {
      fn((k: string, o?: { values?: Record<string, unknown> }) =>
        o?.values ? `${k}:${Object.values(o.values).join('|')}` : k,
      );
      return () => {};
    },
  },
  locale: {
    subscribe: (fn: (v: string) => void) => {
      fn('en');
      return () => {};
    },
  },
}));
// Leaflet needs a real browser.
vi.mock('./PlanMap.svelte', () => ({ default: vi.fn() }));

const card = (title: string) => ({
  title,
  why: `why ${title}`,
  category: 'food',
  best_time: 'evening' as const,
  on_wikipedia: title === 'Time Out',
  lat: title === 'Time Out' ? 38.7 : null,
  lon: title === 'Time Out' ? -9.1 : null,
  image_url: title === 'Time Out' ? 'https://upload.wikimedia.org/x.jpg' : null,
  image_page: title === 'Time Out' ? 'https://en.wikipedia.org/wiki/X' : null,
});

function setup(target: { stopId?: string; date?: string; label: string } = { stopId: 's1', label: 'Lisbon' }) {
  const onAdd = vi.fn().mockResolvedValue({ lat: 38.7, lon: -9.1 });
  const onclose = vi.fn();
  render(SuggestPanel, { props: { tripId: 't1', target, onAdd, onclose } });
  return { onAdd, onclose };
}

describe('SuggestPanel', () => {
  // Braces: an arrow returning the mock would hand Vitest a teardown function.
  beforeEach(() => {
    mockSuggest.mockReset();
    forgetSuggestions();
  });

  it('asks for the stop with the picked interests and the wish', async () => {
    mockSuggest.mockResolvedValue({ city: 'Lisbon', day: null, suggestions: [card('Time Out')], unverified: 0 });
    setup();
    await fireEvent.click(screen.getByText(/suggest.interest_food/));
    await fireEvent.input(screen.getByPlaceholderText('suggest.wish_placeholder'), { target: { value: 'rainy day' } });
    await fireEvent.click(screen.getByText('suggest.ask'));

    await screen.findByText('Time Out');
    expect(mockSuggest).toHaveBeenCalledWith('t1', {
      stop_id: 's1',
      date: null,
      interests: ['food'],
      wish: 'rainy day',
      exclude: [],
    });
    expect(screen.getByText('why Time Out')).toBeTruthy();
  });

  it('shows a photo when there is one and a maps link on every card', async () => {
    mockSuggest.mockResolvedValue({
      city: 'Lisbon',
      day: null,
      suggestions: [card('Time Out'), card('Café X')],
      unverified: 0,
    });
    const { container } = render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await screen.findByText('Café X');
    const imgs = container.querySelectorAll('.sg-thumb img');
    expect(imgs).toHaveLength(1);
    expect(imgs[0].getAttribute('src')).toBe('https://upload.wikimedia.org/x.jpg');
    const links = [...container.querySelectorAll<HTMLAnchorElement>('.sg-photos')].map((a) => a.href);
    expect(links).toHaveLength(2);
    expect(links[1]).toBe('https://www.google.com/maps/search/?api=1&query=Caf%C3%A9%20X%2C%20Lisbon');
  });

  it('adds a card once, through the planner', async () => {
    mockSuggest.mockResolvedValue({ city: 'Lisbon', day: null, suggestions: [card('Time Out')], unverified: 0 });
    const { onAdd } = setup();
    await fireEvent.click(screen.getByText('suggest.ask'));
    const add = await screen.findByLabelText(/^suggest\.add/);
    await fireEvent.click(add);
    await waitFor(() => expect(add.textContent).toBe('✓'));
    await fireEvent.click(add);
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onAdd.mock.calls[0][0].title).toBe('Time Out');
  });

  it('"more" excludes what is already shown and appends', async () => {
    mockSuggest
      .mockResolvedValueOnce({ city: 'Lisbon', day: '2027-05-12', suggestions: [card('A')], unverified: 0 })
      .mockResolvedValueOnce({ city: 'Lisbon', day: '2027-05-12', suggestions: [card('B')], unverified: 2 });
    setup({ date: '2027-05-12', label: 'Lisbon · Wed 12' });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await screen.findByText('A');
    await fireEvent.click(screen.getByText('suggest.more'));
    await screen.findByText('B');
    expect(screen.getByText('A')).toBeTruthy();
    expect(mockSuggest.mock.calls[1][1]).toMatchObject({ date: '2027-05-12', exclude: ['A'] });
  });

  it('explains the daily limit in words', async () => {
    mockSuggest.mockRejectedValue(new Error('daily_limit'));
    setup();
    await fireEvent.click(screen.getByText('suggest.ask'));
    expect((await screen.findByRole('alert')).textContent).toBe('suggest.error_daily_limit');
  });

  it('closes on Escape', async () => {
    const { onclose } = setup();
    await fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onclose).toHaveBeenCalled();
  });

  it('says so when a place was added without a pin', async () => {
    mockSuggest.mockResolvedValue({ city: 'Lisbon', day: null, suggestions: [card('Café X')], unverified: 0 });
    const onAdd = vi.fn().mockResolvedValue(null);
    render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd, onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await fireEvent.click(await screen.findByLabelText(/^suggest\.add/));
    expect(await screen.findByText('suggest.added_without_pin')).toBeTruthy();
  });

  it('shows how far a placed card is from the booked stay', async () => {
    mockSuggest.mockResolvedValue({
      city: 'Lisbon',
      day: null,
      stay: { name: 'Casa', lat: 38.71, lon: -9.14 },
      suggestions: [card('Time Out'), card('Café X')],
      unverified: 0,
    });
    const { container } = render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await screen.findByText('Café X');
    const far = [...container.querySelectorAll('.sg-far')].map((e) => e.textContent);
    // Only Time Out has a position; Café X gets one when it is added.
    expect(far).toHaveLength(1);
    expect(far[0]).toMatch(/suggest\.from_stay:\d.* km\|Casa/);
  });

  it('a place found on the map when added gets its distance too', async () => {
    mockSuggest.mockResolvedValue({
      city: 'Lisbon',
      day: null,
      stay: { name: 'Casa', lat: 38.71, lon: -9.14 },
      suggestions: [card('Café X')],
      unverified: 0,
    });
    const onAdd = vi.fn().mockResolvedValue({ lat: 38.72, lon: -9.15 });
    const { container } = render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd, onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await fireEvent.click(await screen.findByLabelText(/^suggest\.add/));
    await waitFor(() => expect(container.querySelectorAll('.sg-far')).toHaveLength(1));
  });

  it('remembers the last list when reopened, without asking again', async () => {
    mockSuggest.mockResolvedValue({ city: 'Lisbon', day: null, suggestions: [card('Time Out')], unverified: 0 });
    const first = render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await screen.findByText('Time Out');
    first.unmount();

    render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    expect(screen.getByText('Time Out')).toBeTruthy();
    expect(mockSuggest).toHaveBeenCalledTimes(1);
  });

  it('another stop starts with an empty list', async () => {
    mockSuggest.mockResolvedValue({ city: 'Lisbon', day: null, suggestions: [card('Time Out')], unverified: 0 });
    const first = render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await screen.findByText('Time Out');
    first.unmount();
    render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's2', label: 'Porto' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    expect(screen.queryByText('Time Out')).toBeNull();
  });

  it('draws a map only when some card has a position', async () => {
    mockSuggest.mockResolvedValue({ city: 'Lisbon', day: null, suggestions: [card('Café X')], unverified: 0 });
    const { container } = render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await screen.findByText('Café X');
    expect(container.querySelector('.sg-map')).toBeNull();
    expect(screen.queryByLabelText(/^suggest\.show_map_named/)).toBeNull();
  });

  it('"show on map" picks out that card, numbered like its pin', async () => {
    mockSuggest.mockResolvedValue({
      city: 'Lisbon',
      day: null,
      suggestions: [card('Café X'), card('Time Out')],
      unverified: 0,
    });
    const { container } = render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await screen.findByText('Time Out');
    expect(container.querySelector('.sg-map')).not.toBeNull();
    // Only the placed card is numbered and has the button.
    const buttons = screen.getAllByLabelText(/^suggest\.show_map_named/);
    expect(buttons).toHaveLength(1);
    expect(container.querySelector('.sg-num')?.textContent).toBe('1');
    await fireEvent.click(buttons[0]);
    expect(container.querySelector('.sg-card.selected')?.textContent).toContain('Time Out');
  });

  it('says when the booked stay has no location, instead of guessing one', async () => {
    mockSuggest.mockResolvedValue({
      city: 'Chengdu',
      day: null,
      stay: null,
      stay_without_pin: 'IntercityHotel',
      suggestions: [card('Time Out')],
      unverified: 0,
    });
    const { container } = render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Chengdu' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    expect((await screen.findByText(/suggest\.stay_without_pin/)).textContent).toContain('IntercityHotel');
    expect(container.querySelector('.sg-far')).toBeNull();
  });

  it('stops offering "more" once the list is as long as the server can leave out', async () => {
    mockSuggest.mockResolvedValue({
      city: 'Lisbon',
      day: null,
      suggestions: Array.from({ length: 61 }, (_, i) => card(`P${i}`)),
      unverified: 0,
    });
    setup();
    await fireEvent.click(screen.getByText('suggest.ask'));
    await screen.findByText('P60');
    expect(screen.queryByText('suggest.more')).toBeNull();
  });

  it('an add that finishes after the panel closed is still remembered', async () => {
    mockSuggest.mockResolvedValue({ city: 'Lisbon', day: null, suggestions: [card('Time Out')], unverified: 0 });
    let finish: (v: { lat: number; lon: number }) => void = () => {};
    const onAdd = vi.fn(() => new Promise<{ lat: number; lon: number }>((r) => (finish = r)));
    const first = render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd, onclose: vi.fn() },
    });
    await fireEvent.click(screen.getByText('suggest.ask'));
    await fireEvent.click(await screen.findByLabelText(/^suggest\.add/));
    first.unmount();
    finish({ lat: 38.7, lon: -9.1 });
    await new Promise((r) => setTimeout(r, 0));

    render(SuggestPanel, {
      props: { tripId: 't1', target: { stopId: 's1', label: 'Lisbon' }, onAdd: vi.fn(), onclose: vi.fn() },
    });
    expect(screen.getByLabelText(/^suggest\.add/).textContent).toBe('✓');
  });
});
