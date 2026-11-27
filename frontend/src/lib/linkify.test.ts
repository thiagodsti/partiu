import { describe, it, expect } from 'vitest';
import { splitLinks } from './linkify';

describe('splitLinks', () => {
  it('shortens a long booking link to its site', () => {
    expect(splitLinks('Reservar aqui https://www.booking.com/hotel/pt/x.html?aid=1&label=abc')).toEqual([
      { text: 'Reservar aqui ' },
      { url: 'https://www.booking.com/hotel/pt/x.html?aid=1&label=abc', label: 'booking.com' },
    ]);
  });

  it('leaves sentence punctuation outside the link', () => {
    expect(splitLinks('see https://example.com/a.')).toEqual([
      { text: 'see ' },
      { url: 'https://example.com/a', label: 'example.com' },
      { text: '.' },
    ]);
  });

  it('links nothing that is not http(s)', () => {
    expect(splitLinks('javascript:alert(1) and plain text')).toEqual([{ text: 'javascript:alert(1) and plain text' }]);
  });

  it('keeps a bracket the URL opened, drops one around it', () => {
    expect(splitLinks('https://en.wikipedia.org/wiki/Fado_(music)')).toEqual([
      { url: 'https://en.wikipedia.org/wiki/Fado_(music)', label: 'en.wikipedia.org' },
    ]);
    expect(splitLinks('(see https://example.com/a).')).toEqual([
      { text: '(see ' },
      { url: 'https://example.com/a', label: 'example.com' },
      { text: ').' },
    ]);
  });
});
