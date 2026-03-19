import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import LoadingScreen from './LoadingScreen.svelte';

describe('LoadingScreen', () => {
  it('renders the default message', () => {
    const { getByText } = render(LoadingScreen, { props: {} });
    expect(getByText('Loading...')).toBeInTheDocument();
  });

  it('renders a custom message', () => {
    const { getByText } = render(LoadingScreen, { props: { message: 'Fetching trips…' } });
    expect(getByText('Fetching trips…')).toBeInTheDocument();
  });

  it('renders the default icon', () => {
    const { container } = render(LoadingScreen, { props: {} });
    expect(container.querySelector('.loading-icon')!.textContent).toBe('✈');
  });

  it('renders a custom icon', () => {
    const { container } = render(LoadingScreen, { props: { icon: '🔄' } });
    expect(container.querySelector('.loading-icon')!.textContent).toBe('🔄');
  });
});
