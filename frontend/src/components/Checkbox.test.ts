import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import Checkbox from './Checkbox.svelte';

const props = { checked: false, label: 'Mark item', onToggle: vi.fn() };

describe('Checkbox', () => {
  it('exposes its state to assistive tech', () => {
    const { container } = render(Checkbox, { props });
    const box = container.querySelector('.checkbox') as HTMLButtonElement;
    expect(box.getAttribute('role')).toBe('checkbox');
    expect(box.getAttribute('aria-checked')).toBe('false');
    expect(box.getAttribute('aria-label')).toBe('Mark item');
  });

  it('reports itself as checked when it is', () => {
    const { container } = render(Checkbox, { props: { ...props, checked: true } });
    expect(container.querySelector('.checkbox')!.getAttribute('aria-checked')).toBe('true');
  });

  it('calls onToggle when clicked', async () => {
    const onToggle = vi.fn();
    const { container } = render(Checkbox, { props: { ...props, onToggle } });
    await fireEvent.click(container.querySelector('.checkbox')!);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  // A day-planner card toggles open when its body is clicked, so a checkbox
  // inside one has to keep its click to itself or ticking an item also
  // collapses the card under it.
  it('does not let the click reach an enclosing handler', async () => {
    const onParent = vi.fn();
    const wrapper = document.createElement('div');
    const target = document.createElement('div');
    wrapper.appendChild(target);
    document.body.appendChild(wrapper);
    wrapper.addEventListener('click', onParent);

    render(Checkbox, { props, target });
    await fireEvent.click(target.querySelector('.checkbox')!);

    expect(onParent).not.toHaveBeenCalled();
    wrapper.remove();
  });

  // The tick is painted in --accent-on, not white: on the graphite preset in
  // dark mode the accent fill is near-white, and a hardcoded white tick was
  // invisible on it.
  it('paints the tick in the accent-on token so it reads on every preset', () => {
    const { container } = render(Checkbox, { props: { ...props, checked: true } });
    const tick = container.querySelector('svg path') as SVGPathElement;
    expect(tick.getAttribute('stroke')).toBe('var(--accent-on)');
    const box = container.querySelector('svg rect') as SVGRectElement;
    expect(box.getAttribute('fill')).toBe('var(--accent)');
  });

  it('draws an empty box when unchecked', () => {
    const { container } = render(Checkbox, { props });
    expect(container.querySelector('svg path')).toBeNull();
    expect(container.querySelector('svg rect')!.getAttribute('stroke')).toBe('var(--border-strong)');
  });
});
