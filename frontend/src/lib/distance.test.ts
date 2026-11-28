import { describe, it, expect } from 'vitest';
import { formatKm, kmBetween } from './distance';

describe('distance', () => {
  it('measures Lisbon centre to Belém at about 7 km', () => {
    const d = kmBetween([38.7223, -9.1393], [38.6916, -9.216]);
    expect(d).toBeGreaterThan(6);
    expect(d).toBeLessThan(8);
  });

  it('is zero for the same point', () => {
    expect(kmBetween([10, 10], [10, 10])).toBe(0);
  });

  it('prints metres under a kilometre and rounds the rest', () => {
    expect(formatKm(0.34)).toBe('350 m');
    expect(formatKm(0.01)).toBe('100 m');
    expect(formatKm(1.234)).toBe('1.2 km');
    expect(formatKm(1.234, 'pt-BR')).toBe('1,2 km');
    expect(formatKm(14.6)).toBe('15 km');
  });
});
