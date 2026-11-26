/* The review page's chips: values found in an email, clicked into a field.
 * Kept out of the component so the date/time merging is unit-tested. */

export type ChipKind = 'flight' | 'airport' | 'date' | 'time' | 'ref';
export type LegField =
  | 'flight_number'
  | 'departure_airport'
  | 'arrival_airport'
  | 'departure_datetime'
  | 'arrival_datetime'
  | 'booking_reference';

const MONTHS: Record<string, number> = {
  jan: 1, feb: 2, fev: 2, mar: 3, apr: 4, abr: 4, may: 5, mai: 5, maj: 5, jun: 6,
  jul: 7, aug: 8, ago: 8, sep: 9, set: 9, oct: 10, out: 10, okt: 10, nov: 11, dec: 12, dez: 12,
};

const pad = (n: number) => String(n).padStart(2, '0');

function iso(y: number, m: number, d: number): string | null {
  if (m < 1 || m > 12 || d < 1) return null;
  // The day must exist in that month and year: no 31 February, 29 February
  // only in leap years.
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  if (d > last) return null;
  return `${y}-${pad(m)}-${pad(d)}`;
}

/** A date chip as "YYYY-MM-DD", or null when it cannot be read. Day-first for
 *  numeric dates (the European and Brazilian convention these emails use); a
 *  missing year is taken from `fallbackYear`. */
export function parseDateChip(text: string, fallbackYear = new Date().getFullYear()): string | null {
  const s = text.trim().toLowerCase();
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) return iso(+m[1], +m[2], +m[3]);
  m = s.match(/^(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})$/);
  if (m) {
    const y = m[3].length === 2 ? 2000 + +m[3] : +m[3];
    return iso(y, +m[2], +m[1]);
  }
  m = s.match(/^(\d{1,2})\s?([a-zç]{3})[a-zç]*\.?(?:\s?(\d{2,4}))?$/);
  if (m && MONTHS[m[2]]) {
    const y = m[3] ? (m[3].length === 2 ? 2000 + +m[3] : +m[3]) : fallbackYear;
    return iso(y, MONTHS[m[2]], +m[1]);
  }
  m = s.match(/^([a-zç]{3})[a-zç]*\.?\s(\d{1,2})(?:,?\s(\d{4}))?$/);
  if (m && MONTHS[m[1]]) return iso(m[3] ? +m[3] : fallbackYear, MONTHS[m[1]], +m[2]);
  return null;
}

/** The field's new value after clicking a chip into it, or null when the chip
 *  does not fit that field (a time into an airport, say). Dates and times
 *  merge into a datetime field: the half that is not clicked is kept.
 *
 *  A date chip without a year ("16 NOV") takes the year the field already
 *  holds, else the year of `emailDate` ("YYYY-MM-DD", the day the email was
 *  sent) — the year the backend resolves such dates against too. A chip that
 *  states its year keeps it. A time chip into an empty field fills in the
 *  email's date as a stand-in, so the order the chips are tapped in does not
 *  change the year. */
export function applyChip(
  field: LegField,
  current: string,
  kind: ChipKind,
  value: string,
  emailDate: string = new Date().toISOString().slice(0, 10),
): string | null {
  const isDateTime = field === 'departure_datetime' || field === 'arrival_datetime';
  const emailYear = Number(emailDate.slice(0, 4));
  if (isDateTime) {
    const [d, t] = (current || '').split('T');
    if (kind === 'date') {
      const fieldYear = /^\d{4}/.test(d || '') ? Number(d.slice(0, 4)) : null;
      const day = parseDateChip(value, fieldYear ?? emailYear);
      return day ? `${day}T${t || '00:00'}` : null;
    }
    if (kind === 'time') {
      // An empty field gets the email's own date as a stand-in, never today's:
      // a year-less date chip clicked next then keeps the email's year.
      const day = d || emailDate;
      return `${day}T${value}`;
    }
    return null;
  }
  if (field === 'flight_number') return kind === 'flight' ? value : null;
  if (field === 'departure_airport' || field === 'arrival_airport') {
    return kind === 'airport' ? value : null;
  }
  if (field === 'booking_reference') return kind === 'ref' ? value : null;
  return null;
}

/** Split a line into plain and highlighted pieces, for rendering without HTML. */
export function highlight(line: string, needles: string[]): { text: string; hit: boolean }[] {
  const terms = needles.filter((n) => n && n.length >= 2);
  if (!terms.length) return [{ text: line, hit: false }];
  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const re = new RegExp(`(${escaped.join('|')})`, 'g');
  const out: { text: string; hit: boolean }[] = [];
  let last = 0;
  for (const m of line.matchAll(re)) {
    if (m.index! > last) out.push({ text: line.slice(last, m.index), hit: false });
    out.push({ text: m[0], hit: true });
    last = m.index! + m[0].length;
  }
  if (last < line.length) out.push({ text: line.slice(last), hit: false });
  return out;
}
