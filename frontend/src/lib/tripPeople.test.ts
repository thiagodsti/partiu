import { describe, it, expect } from 'vitest';
import { tripPeople } from './utils';

describe('tripPeople', () => {
  it('returns null for a solo trip rather than "1 person"', () => {
    // A trip with nobody else on it is the normal case; saying so on every
    // card is the row of noughts tripContents already refuses to print.
    expect(tripPeople(0, 0, 0)).toBeNull();
  });

  it('adds the owner, who holds no share row of their own', () => {
    expect(tripPeople(1, 0, 0)).toEqual({ people: 2, pending: 0 });
  });

  it('counts roster guests as people', () => {
    // Three guests and no collaborators is four people, not a solo trip —
    // the case that prompted the per-trip roster in the first place.
    expect(tripPeople(0, 0, 3)).toEqual({ people: 4, pending: 0 });
  });

  it('keeps pending invitations out of the head count', () => {
    // Someone invited has not joined: adding them in would claim a companion
    // who may still decline.
    expect(tripPeople(0, 2, 0)).toEqual({ people: 1, pending: 2 });
  });

  it('sums collaborators and guests', () => {
    expect(tripPeople(2, 1, 3)).toEqual({ people: 6, pending: 1 });
  });

  it('surfaces a trip that has only an outstanding invitation', () => {
    // Nobody has accepted yet, but something is happening and the card should
    // say so rather than render nothing.
    expect(tripPeople(0, 1, 0)).not.toBeNull();
  });

  it('defaults the optional counts', () => {
    expect(tripPeople(1)).toEqual({ people: 2, pending: 0 });
  });
});
