/* The day note's stored shape, shared by the trip page's day cards and the
 * planner so both read and write the same thing.
 *
 * A note is JSON `{ note, items }`. `items` was the day card's own checklist;
 * migration 0041 moved those into the planner's items, so it is always written
 * empty now and only read for notes saved by an older client. Older shapes are
 * still accepted on read: a legacy block array, and plain text. */

export interface LegacyChecklistItem {
  text: string;
  checked: boolean;
}

export interface DayNoteContent {
  note: string;
  items: LegacyChecklistItem[];
}

export function parseDayNote(raw: string | null | undefined): DayNoteContent {
  if (!raw) return { note: '', items: [] };
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return { note: parsed.note ?? '', items: parsed.items ?? [] };
    }
    if (Array.isArray(parsed)) {
      const textBlock = parsed.find((b: { type: string }) => b.type === 'text');
      const checkBlock = parsed.find((b: { type: string }) => b.type === 'checklist');
      return { note: textBlock?.value ?? '', items: checkBlock?.items ?? [] };
    }
    // A bare JSON scalar ("42", "true") is text someone typed.
    return { note: raw, items: [] };
  } catch {
    return { note: raw, items: [] };
  }
}

export function serializeDayNote(note: string): string {
  return JSON.stringify({ note, items: [] });
}
