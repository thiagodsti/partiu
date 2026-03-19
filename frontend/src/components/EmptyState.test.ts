import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import EmptyState from './EmptyState.svelte';

describe('EmptyState', () => {
  it('renders the title', () => {
    const { getByText } = render(EmptyState, { props: { title: 'Nothing here' } });
    expect(getByText('Nothing here')).toBeInTheDocument();
  });

  it('renders the default icon when none provided', () => {
    const { container } = render(EmptyState, { props: { title: 'Empty' } });
    expect(container.querySelector('.empty-state-icon')!.textContent).toBe('✈');
  });

  it('renders a custom icon', () => {
    const { container } = render(EmptyState, { props: { title: 'Empty', icon: '⚠️' } });
    expect(container.querySelector('.empty-state-icon')!.textContent).toBe('⚠️');
  });

  it('renders description when provided', () => {
    const { getByText } = render(EmptyState, {
      props: { title: 'Empty', description: 'No flights found' },
    });
    expect(getByText('No flights found')).toBeInTheDocument();
  });

  it('does not render description element when omitted', () => {
    const { container } = render(EmptyState, { props: { title: 'Empty' } });
    expect(container.querySelector('.empty-state-desc')).toBeNull();
  });
});
