import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import AirportCombobox from './AirportCombobox.svelte';

const { mockSearch } = vi.hoisted(() => ({ mockSearch: vi.fn() }));

vi.mock('../api/client', () => ({
  airportsApi: { search: mockSearch },
}));

const GRU = {
  iata_code: 'GRU',
  name: 'Guarulhos International Airport',
  city_name: 'São Paulo',
  country_code: 'BR',
  latitude: -23.43,
  longitude: -46.47,
};

const SCL = {
  iata_code: 'SCL',
  name: 'Arturo Merino Benitez Airport',
  city_name: 'Santiago',
  country_code: 'CL',
  latitude: -33.39,
  longitude: -70.79,
};

describe('AirportCombobox', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders a text input', () => {
    const { container } = render(AirportCombobox, { props: { value: '' } });
    expect(container.querySelector('input[type="text"]')).toBeInTheDocument();
  });

  it('renders with placeholder', () => {
    const { container } = render(AirportCombobox, {
      props: { value: '', placeholder: 'Search airports' },
    });
    expect((container.querySelector('input') as HTMLInputElement).placeholder).toBe(
      'Search airports',
    );
  });

  it('marks input required when required prop is true', () => {
    const { container } = render(AirportCombobox, {
      props: { value: '', required: true },
    });
    expect((container.querySelector('input') as HTMLInputElement).required).toBe(true);
  });

  it('does not show dropdown initially', () => {
    const { container } = render(AirportCombobox, { props: { value: '' } });
    expect(container.querySelector('.airport-suggestions')).toBeNull();
  });

  it('calls airportsApi.search after debounce on input', async () => {
    mockSearch.mockResolvedValue([GRU]);
    const { container } = render(AirportCombobox, { props: { value: '' } });
    const input = container.querySelector('input')!;

    await fireEvent.input(input, { target: { value: 'GRU' } });
    expect(mockSearch).not.toHaveBeenCalled();

    vi.advanceTimersByTime(250);
    await waitFor(() => expect(mockSearch).toHaveBeenCalledWith('GRU'));
  });

  it('shows suggestions dropdown after search returns results', async () => {
    mockSearch.mockResolvedValue([GRU, SCL]);
    const { container } = render(AirportCombobox, { props: { value: '' } });
    const input = container.querySelector('input')!;

    await fireEvent.input(input, { target: { value: 'gr' } });
    vi.advanceTimersByTime(250);
    await waitFor(() => {
      expect(container.querySelector('.airport-suggestions')).toBeInTheDocument();
    });
    expect(container.querySelectorAll('.airport-suggestion-item')).toHaveLength(2);
  });

  it('does not show dropdown when search returns empty', async () => {
    mockSearch.mockResolvedValue([]);
    const { container } = render(AirportCombobox, { props: { value: '' } });
    await fireEvent.input(container.querySelector('input')!, { target: { value: 'ZZZ' } });
    vi.advanceTimersByTime(250);
    await waitFor(() => expect(mockSearch).toHaveBeenCalled());
    expect(container.querySelector('.airport-suggestions')).toBeNull();
  });

  it('shows IATA code and airport detail in suggestions', async () => {
    mockSearch.mockResolvedValue([GRU]);
    const { container, findByText } = render(AirportCombobox, { props: { value: '' } });
    await fireEvent.input(container.querySelector('input')!, { target: { value: 'GRU' } });
    vi.advanceTimersByTime(250);
    expect(await findByText('GRU')).toBeInTheDocument();
    expect(
      await findByText('Guarulhos International Airport, BR'),
    ).toBeInTheDocument();
  });

  it('clears dropdown when input is emptied', async () => {
    mockSearch.mockResolvedValue([GRU]);
    const { container } = render(AirportCombobox, { props: { value: '' } });
    const input = container.querySelector('input')!;

    await fireEvent.input(input, { target: { value: 'GRU' } });
    vi.advanceTimersByTime(250);
    await waitFor(() => expect(container.querySelector('.airport-suggestions')).toBeInTheDocument());

    await fireEvent.input(input, { target: { value: '' } });
    expect(container.querySelector('.airport-suggestions')).toBeNull();
  });

  it('closes dropdown on Escape key', async () => {
    mockSearch.mockResolvedValue([GRU]);
    const { container } = render(AirportCombobox, { props: { value: '' } });
    const input = container.querySelector('input')!;

    await fireEvent.input(input, { target: { value: 'GRU' } });
    vi.advanceTimersByTime(250);
    await waitFor(() => expect(container.querySelector('.airport-suggestions')).toBeInTheDocument());

    await fireEvent.keyDown(input, { key: 'Escape' });
    expect(container.querySelector('.airport-suggestions')).toBeNull();
  });

  it('highlights item on ArrowDown and selects on Enter', async () => {
    mockSearch.mockResolvedValue([GRU, SCL]);
    const { container } = render(AirportCombobox, { props: { value: '' } });
    const input = container.querySelector('input')!;

    await fireEvent.input(input, { target: { value: 'G' } });
    vi.advanceTimersByTime(250);
    await waitFor(() => expect(container.querySelector('.airport-suggestions')).toBeInTheDocument());

    await fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(container.querySelector('.airport-suggestion-item.active')).toBeInTheDocument();

    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(container.querySelector('.airport-suggestions')).toBeNull();
    // After selecting, the input should show the formatted suggestion
    expect((input as HTMLInputElement).value).toContain('GRU');
  });
});
