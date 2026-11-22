import { describe, it, expect } from 'vitest';
import { parseDayNote, serializeDayNote } from './dayNotes';

describe('parseDayNote', () => {
  it('reads the current JSON shape', () => {
    expect(parseDayNote('{"note":"hi","items":[]}')).toEqual({ note: 'hi', items: [] });
  });
  it('reads a legacy block array', () => {
    const raw = JSON.stringify([
      { type: 'text', value: 'old' },
      { type: 'checklist', items: [{ text: 'a', checked: true }] },
    ]);
    expect(parseDayNote(raw)).toEqual({ note: 'old', items: [{ text: 'a', checked: true }] });
  });
  it('treats plain text and bare scalars as the note', () => {
    expect(parseDayNote('just text')).toEqual({ note: 'just text', items: [] });
    expect(parseDayNote('42')).toEqual({ note: '42', items: [] });
    expect(parseDayNote('')).toEqual({ note: '', items: [] });
  });
  it('keeps a legacy checklist when saving the note', () => {
    const legacy = [{ text: 'old', checked: false }];
    expect(parseDayNote(serializeDayNote('n', legacy))).toEqual({ note: 'n', items: legacy });
  });
  it('round-trips through serializeDayNote', () => {
    expect(parseDayNote(serializeDayNote('Levar casaco')).note).toBe('Levar casaco');
  });
});
