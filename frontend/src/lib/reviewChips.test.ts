import { describe, it, expect } from 'vitest';
import { applyChip, highlight, parseDateChip } from './reviewChips';

describe('parseDateChip', () => {
  it('reads ISO, day-first numeric and month-name dates', () => {
    expect(parseDateChip('2026-03-13')).toBe('2026-03-13');
    expect(parseDateChip('15/07/2026')).toBe('2026-07-15');
    expect(parseDateChip('15.07.26')).toBe('2026-07-15');
    expect(parseDateChip('21 Jan 2018')).toBe('2018-01-21');
    expect(parseDateChip('16 NOV', 2018)).toBe('2018-11-16');
    expect(parseDateChip('Mar 13, 2027')).toBe('2027-03-13');
  });

  it('reads Portuguese and Swedish month names', () => {
    expect(parseDateChip('3 dez 2026')).toBe('2026-12-03');
    expect(parseDateChip('29 okt 2026')).toBe('2026-10-29');
  });

  it('refuses what is not a date', () => {
    expect(parseDateChip('32/01/2026')).toBeNull();
    expect(parseDateChip('hello')).toBeNull();
  });
});

describe('applyChip', () => {
  it('fills the matching kind of field only', () => {
    expect(applyChip('flight_number', '', 'flight', 'LA8072')).toBe('LA8072');
    expect(applyChip('departure_airport', '', 'airport', 'GRU')).toBe('GRU');
    expect(applyChip('departure_airport', '', 'time', '07:30')).toBeNull();
    expect(applyChip('flight_number', '', 'airport', 'GRU')).toBeNull();
  });

  it('merges a date or a time into a datetime field, keeping the other half', () => {
    const withDate = applyChip('departure_datetime', '', 'date', '16 NOV 2018');
    expect(withDate).toBe('2018-11-16T00:00');
    expect(applyChip('departure_datetime', withDate!, 'time', '15:40')).toBe('2018-11-16T15:40');
    expect(applyChip('arrival_datetime', '2018-11-16T17:00', 'date', '17/11/2018')).toBe(
      '2018-11-17T17:00',
    );
  });

  it('refuses a date it cannot read', () => {
    expect(applyChip('departure_datetime', '2018-11-16T15:40', 'date', 'soon')).toBeNull();
  });
});

describe('highlight', () => {
  it('splits a line into plain and highlighted parts', () => {
    expect(highlight('Voo O66175 FLN → GRU', ['O66175', 'GRU'])).toEqual([
      { text: 'Voo ', hit: false },
      { text: 'O66175', hit: true },
      { text: ' FLN → ', hit: false },
      { text: 'GRU', hit: true },
    ]);
  });

  it('treats needles as text, not patterns', () => {
    expect(highlight('price (A+B)', ['(A+B)'])).toEqual([
      { text: 'price ', hit: false },
      { text: '(A+B)', hit: true },
    ]);
  });

  it('returns the line whole when there is nothing to mark', () => {
    expect(highlight('nothing here', [])).toEqual([{ text: 'nothing here', hit: false }]);
  });
});

describe('review follow-ups', () => {
  it('refuses days that do not exist in the month, keeps leap days', () => {
    expect(parseDateChip('31/02/2026')).toBeNull();
    expect(parseDateChip('29/02/2026')).toBeNull();
    expect(parseDateChip('29/02/2028')).toBe('2028-02-29');
    expect(parseDateChip('31 apr 2026')).toBeNull();
  });

  it('a year-less chip takes the field year, else the email year', () => {
    expect(applyChip('departure_datetime', '2018-11-15T15:40', 'date', '16 NOV', 2026)).toBe(
      '2018-11-16T15:40',
    );
    expect(applyChip('departure_datetime', '', 'date', '16 NOV', 2018)).toBe('2018-11-16T00:00');
    // A chip that states its year keeps it.
    expect(applyChip('departure_datetime', '2018-11-15T15:40', 'date', '16 NOV 2019', 2018)).toBe(
      '2019-11-16T15:40',
    );
  });
});
