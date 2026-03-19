import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from '@testing-library/svelte';
import ToastContainer from './ToastContainer.svelte';

type Toast = { id: number; message: string; type: string };

// Hand-rolled store to avoid calling writable() inside vi.hoisted()
const { testToasts } = vi.hoisted(() => {
  let _val: Toast[] = [];
  const _subs = new Set<(v: Toast[]) => void>();
  return {
    testToasts: {
      subscribe(fn: (v: Toast[]) => void) {
        _subs.add(fn);
        fn(_val);
        return () => { _subs.delete(fn); };
      },
      set(v: Toast[]) {
        _val = v;
        _subs.forEach((fn) => fn(v));
      },
    },
  };
});

vi.mock('../lib/toastStore', () => ({ toasts: testToasts }));

describe('ToastContainer', () => {
  beforeEach(() => testToasts.set([]));
  afterEach(() => testToasts.set([]));

  it('renders nothing when there are no toasts', () => {
    const { container } = render(ToastContainer);
    expect(container.querySelector('.toast-container')).toBeNull();
  });

  it('renders a toast message', async () => {
    testToasts.set([{ id: 1, message: 'Hello world', type: 'info' }]);
    const { findByText } = render(ToastContainer);
    expect(await findByText('Hello world')).toBeInTheDocument();
  });

  it('renders multiple toasts', async () => {
    testToasts.set([
      { id: 1, message: 'First', type: 'info' },
      { id: 2, message: 'Second', type: 'success' },
    ]);
    const { findByText } = render(ToastContainer);
    expect(await findByText('First')).toBeInTheDocument();
    expect(await findByText('Second')).toBeInTheDocument();
  });

  it('applies the correct type class', async () => {
    testToasts.set([{ id: 1, message: 'Error!', type: 'error' }]);
    const { container } = render(ToastContainer);
    // wait a tick for reactive update
    await Promise.resolve();
    const toast = container.querySelector('.toast-error');
    expect(toast).toBeInTheDocument();
    expect(toast!.textContent).toBe('Error!');
  });

  it('applies success class correctly', async () => {
    testToasts.set([{ id: 1, message: 'Done', type: 'success' }]);
    const { container } = render(ToastContainer);
    await Promise.resolve();
    expect(container.querySelector('.toast-success')).toBeInTheDocument();
  });
});
