import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import FormSection from './FormSection.svelte';

const childSnippet = createRawSnippet(() => ({
  render: () => '<p class="child-content">hello</p>',
}));

describe('FormSection', () => {
  it('renders children', () => {
    const { container } = render(FormSection, { props: { children: childSnippet } });
    expect(container.querySelector('.child-content')).toBeInTheDocument();
  });

  it('renders title when provided', () => {
    const { container } = render(FormSection, {
      props: { title: 'My Section', children: childSnippet },
    });
    expect(container.querySelector('.form-section-title')!.textContent).toBe('My Section');
  });

  it('does not render title element when omitted', () => {
    const { container } = render(FormSection, { props: { children: childSnippet } });
    expect(container.querySelector('.form-section-title')).toBeNull();
  });

  it('wraps content in a section.form-section element', () => {
    const { container } = render(FormSection, { props: { children: childSnippet } });
    expect(container.querySelector('section.form-section')).toBeInTheDocument();
  });
});
