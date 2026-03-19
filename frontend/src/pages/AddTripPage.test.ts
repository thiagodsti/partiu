import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import AddTripPage from './AddTripPage.svelte';

const { mockPush, mockCreate } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockCreate: vi.fn(),
}));

vi.mock('svelte-spa-router', () => ({ push: mockPush }));
vi.mock('../api/client', () => ({
  tripsApi: { create: mockCreate },
  airportsApi: { search: vi.fn().mockResolvedValue([]) },
}));

// i18n: return key as value so tests work without real translations
vi.mock('../lib/i18n', () => ({
  t: { subscribe: (fn: (v: (key: string) => string) => void) => { fn((k: string) => k); return () => {}; } },
}));

function getNameInput(container: HTMLElement) {
  // The trip name field is the first text input in the form
  return container.querySelector('input[type="text"][required]') as HTMLInputElement;
}

function getBookingRefsInput(container: HTMLElement) {
  // booking_refs is the second input[type="text"] with autocomplete=off
  const inputs = container.querySelectorAll('input[type="text"][autocomplete="off"]');
  return inputs[0] as HTMLInputElement;
}

describe('AddTripPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders form with required name field', () => {
    const { container } = render(AddTripPage);
    const nameInput = getNameInput(container);
    expect(nameInput).toBeInTheDocument();
    expect(nameInput.required).toBe(true);
  });

  it('renders two date inputs', () => {
    const { container } = render(AddTripPage);
    const dateInputs = container.querySelectorAll('input[type="date"]');
    expect(dateInputs).toHaveLength(2);
  });

  it('renders two airport comboboxes (origin, destination)', () => {
    const { container } = render(AddTripPage);
    const comboboxes = container.querySelectorAll('.airport-combobox');
    expect(comboboxes).toHaveLength(2);
  });

  it('renders cancel link pointing to /trips', () => {
    const { container } = render(AddTripPage);
    const cancelLink = container.querySelector('a.btn-secondary') as HTMLAnchorElement;
    expect(cancelLink).toBeInTheDocument();
    expect(cancelLink.getAttribute('href')).toBe('#/trips');
  });

  it('renders submit button', () => {
    const { container } = render(AddTripPage);
    const submitBtn = container.querySelector('button[type="submit"]');
    expect(submitBtn).toBeInTheDocument();
  });

  it('calls tripsApi.create with trimmed name on submit', async () => {
    mockCreate.mockResolvedValue({ id: 'trip-123' });
    const { container } = render(AddTripPage);

    await fireEvent.input(getNameInput(container), { target: { value: '  Paris 2025  ' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Paris 2025' }),
      );
    });
  });

  it('splits booking_refs by comma and uppercases them', async () => {
    mockCreate.mockResolvedValue({ id: 'trip-456' });
    const { container } = render(AddTripPage);

    await fireEvent.input(getNameInput(container), { target: { value: 'Test Trip' } });
    await fireEvent.input(getBookingRefsInput(container), { target: { value: 'abc123, xyz789' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({ booking_refs: ['ABC123', 'XYZ789'] }),
      );
    });
  });

  it('omits booking_refs when empty', async () => {
    mockCreate.mockResolvedValue({ id: 'trip-789' });
    const { container } = render(AddTripPage);

    await fireEvent.change(getNameInput(container), { target: { value: 'No Refs Trip' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      const call = mockCreate.mock.calls[0][0];
      expect(call.booking_refs).toBeUndefined();
    });
  });

  it('shows error message when API fails', async () => {
    mockCreate.mockRejectedValue(new Error('Server error'));
    const { container, findByText } = render(AddTripPage);

    await fireEvent.change(getNameInput(container), { target: { value: 'Failing Trip' } });
    await fireEvent.submit(container.querySelector('form')!);

    const errorMsg = await findByText('Server error');
    expect(errorMsg).toBeInTheDocument();
  });

  it('navigates to new trip on success', async () => {
    mockCreate.mockResolvedValue({ id: 'new-trip-id' });
    const { container } = render(AddTripPage);

    await fireEvent.change(getNameInput(container), { target: { value: 'Success Trip' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/trips/new-trip-id');
    });
  });
});
