<script lang="ts">
  import type { Guest, Trip, TripShare } from '../api/types';
  import { guestsApi } from '../api/client';
  import { currentUser } from '../lib/authStore';
  import { t } from '../lib/i18n';

  /**
   * Who is on this trip: its owner, the accounts it is shared with, and the
   * guests on its roster.
   *
   * The roster is the point of this section. Guest membership used to be
   * *derived* — a guest was "on" a trip if some expense there already named
   * them — which scoped guests correctly but left no way in: a guest created in
   * Settings appeared in no payer select and no split-between list, because no
   * expense named them, and no expense could name them because they were in no
   * list. Migration 0036 makes membership a stated fact and this is where it is
   * stated. What you add here is exactly what the expense form then offers.
   *
   * Collaborators and invitations are **read-only** here. Inviting an account is
   * the owner's business and already lives in the share panel; showing them
   * alongside the guests is what makes this section answer the whole question
   * rather than a third of it.
   */
  interface Props {
    trip: Trip;
    /** Accounts the trip is shared with. Owner-only data — a collaborator gets
     *  an empty list from the API, so this section must read fine without it. */
    collaborators?: TripShare[];
    /** Reports the roster upward so the page can keep its header count live
     *  without re-fetching the trip. */
    onchange?: (guests: Guest[]) => void;
  }
  const { trip, collaborators = [], onchange }: Props = $props();

  let guests = $state<Guest[]>([]);
  let myGuests = $state<Guest[]>([]);
  let loading = $state(true);
  let loadError = $state<string | null>(null);
  let busyId = $state<number | null>(null);
  let actionError = $state<string | null>(null);
  let newName = $state('');
  let adding = $state(false);
  let open = $state(false);
  let highlighted = $state(-1);

  const onTrip = $derived(new Set(guests.map((g) => g.id)));

  /* Accent-folded, mirroring `fold_text` on the backend and `PeoplePicker`'s
   * own search: the names here are typed by hand in a pt-BR app, so "joao" has
   * to find "João". The backend dedupes on the same folding, which is what
   * makes what this box offers and what the server does agree. */
  const fold = (value: string) =>
    value
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase();

  /** Your address book minus whoever is already on this trip — the "someone you
   * have travelled with before" list. Shown as a type-ahead rather than a row
   * of chips: an address book grows and a chip row costs the form its full
   * height on every trip to serve the crowded one. */
  const available = $derived(myGuests.filter((g) => !onTrip.has(g.id)));

  const suggestions = $derived.by(() => {
    const needle = fold(newName.trim());
    return available.filter((g) => !needle || fold(g.name).includes(needle));
  });

  /** The typed name is already on this trip. Checked against the roster rather
   * than left to the server: adding an existing member is a harmless no-op
   * there, so without this the form would look like it did nothing. It also
   * catches a namesake owned by a *collaborator*, whom the address book above
   * cannot see. */
  const alreadyOnTrip = $derived.by(() => {
    const needle = fold(newName.trim());
    return needle ? (guests.find((g) => fold(g.name) === needle) ?? null) : null;
  });

  const accepted = $derived(collaborators.filter((c) => c.status === 'accepted'));
  const pending = $derived(collaborators.filter((c) => c.status === 'pending'));

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [trip_guests, book] = await Promise.all([
        guestsApi.listForTrip(trip.id),
        // Your own book is a convenience, not the roster: failing to load it
        // must not stop the trip's own guests rendering.
        guestsApi.list().catch(() => [] as Guest[]),
      ]);
      guests = trip_guests;
      myGuests = book;
      onchange?.(guests);
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void trip.id;
    load();
  });

  async function add(guestId: number) {
    actionError = null;
    busyId = guestId;
    try {
      await guestsApi.addToTrip(trip.id, guestId);
      newName = '';
      open = false;
      highlighted = -1;
      await load();
    } catch (err) {
      actionError = (err as Error).message;
    } finally {
      busyId = null;
    }
  }

  async function createAndAdd() {
    const name = newName.trim();
    if (!name || adding || alreadyOnTrip) return;
    actionError = null;
    adding = true;
    try {
      // The server reuses an existing guest of the same folded name rather than
      // creating a second one, so typing a name you have used before means that
      // person — no duplicate, whether or not the suggestion was picked.
      const { id } = await guestsApi.create(name);
      await guestsApi.addToTrip(trip.id, id);
      newName = '';
      open = false;
      highlighted = -1;
      await load();
    } catch (err) {
      actionError = (err as Error).message;
    } finally {
      adding = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      open = true;
      if (suggestions.length > 0) highlighted = (highlighted + 1) % suggestions.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (suggestions.length > 0) {
        highlighted = highlighted <= 0 ? suggestions.length - 1 : highlighted - 1;
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      // A highlighted row wins; otherwise Enter submits what was typed, which
      // is how a name nobody has travelled with yet gets added.
      if (highlighted >= 0 && suggestions[highlighted]) add(suggestions[highlighted].id);
      else createAndAdd();
    } else if (e.key === 'Escape') {
      open = false;
      highlighted = -1;
    }
  }

  async function remove(guest: Guest) {
    // Asked rather than done: the row disappears from the expense pickers with
    // it, and × on a list is an easy button to hit by accident. The guest stays
    // in the address book, which is what the message says.
    if (!confirm($t('trip_people.remove_confirm', { values: { name: guest.name } }))) return;
    actionError = null;
    busyId = guest.id;
    try {
      await guestsApi.removeFromTrip(trip.id, guest.id);
      await load();
    } catch {
      // A 409 means an expense on this trip still names them. Saying so beats
      // the raw message, which is the backend's English sentence.
      actionError = $t('trip_people.remove_blocked', { values: { name: guest.name } });
    } finally {
      busyId = null;
    }
  }

  const ownerName = $derived(
    trip.owner_username ?? $currentUser?.username ?? $t('trip_people.owner'),
  );
</script>

<div class="people">
  {#if loading}
    <p class="people-empty">{$t('common.loading')}</p>
  {:else if loadError}
    <p class="people-error">{loadError}</p>
  {:else}
    <ul class="people-list">
      <li class="people-row">
        <span class="people-name">{ownerName}</span>
        <span class="people-tag">{$t('trip_people.owner')}</span>
      </li>
      {#each accepted as collab (collab.user_id)}
        <li class="people-row">
          <span class="people-name">{collab.username}</span>
          <span class="people-tag">{$t('trip_people.collaborator')}</span>
        </li>
      {/each}
      {#each pending as invite (invite.user_id)}
        <li class="people-row">
          <span class="people-name">{invite.username}</span>
          <span class="people-tag">{$t('trip_people.invited')}</span>
        </li>
      {/each}
      {#each guests as guest (guest.id)}
        <li class="people-row">
          <span class="people-name">{guest.name}</span>
          <span class="people-tag">{$t('trip_people.guest')}</span>
          <button
            type="button"
            class="people-remove"
            disabled={busyId === guest.id}
            onclick={() => remove(guest)}
            aria-label={$t('trip_people.remove', { values: { name: guest.name } })}
          >
            ×
          </button>
        </li>
      {/each}
    </ul>

    {#if actionError}
      <p class="people-error">{actionError}</p>
    {/if}

    <form
      class="people-add"
      onsubmit={(e) => {
        e.preventDefault();
        createAndAdd();
      }}
    >
      <div class="people-combo">
        <input
          class="form-input"
          type="text"
          autocomplete="off"
          role="combobox"
          aria-expanded={open}
          aria-controls="trip-people-suggestions"
          bind:value={newName}
          placeholder={$t('trip_people.add_placeholder')}
          aria-label={$t('trip_people.add_placeholder')}
          oninput={() => {
            open = true;
            highlighted = -1;
          }}
          onkeydown={onKeydown}
          onfocus={() => (open = true)}
          onblur={() => setTimeout(() => (open = false), 150)}
        />

        <!-- Opens on focus with the whole book, not only on a match: a box that
             only answers what you already know hides the fact that there is
             anything to pick. Same rule as `PlaceInput` and `PeoplePicker`. -->
        {#if open && suggestions.length > 0}
          <ul class="people-suggestions" id="trip-people-suggestions">
            {#each suggestions as guest, i (guest.id)}
              <li>
                <button
                  type="button"
                  class="people-suggestion"
                  class:highlighted={i === highlighted}
                  disabled={busyId === guest.id}
                  onmousedown={(e) => {
                    e.preventDefault();
                    add(guest.id);
                  }}
                  onmouseenter={() => (highlighted = i)}
                >
                  {guest.name}
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
      <button
        type="submit"
        class="btn btn-secondary"
        disabled={adding || !newName.trim() || !!alreadyOnTrip}
      >
        {adding ? '…' : $t('trip_people.add')}
      </button>
    </form>

    <!-- Says why the button is disabled. A name already on the roster is not an
         error and not a second person, so it reads as a statement. -->
    {#if alreadyOnTrip}
      <p class="people-note">
        {$t('trip_people.already_on_trip', { values: { name: alreadyOnTrip.name } })}
      </p>
    {/if}

    <p class="section-note">{$t('trip_people.hint')}</p>
  {/if}
</div>

<style>
  .people-list {
    list-style: none;
    margin: 0 0 var(--space-md);
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  .people-row {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm) 0;
    border-bottom: 1px solid var(--border);
  }
  .people-row:last-child {
    border-bottom: none;
  }
  .people-name {
    flex: 1 1 auto;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .people-tag {
    flex: 0 0 auto;
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  .people-remove {
    flex: 0 0 auto;
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 1.25rem;
    line-height: 1;
    padding: 0 var(--space-xs);
  }
  .people-remove:hover:not(:disabled) {
    color: var(--danger-text);
  }
  .people-remove:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .people-add {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm);
  }
  /* The combo, not the input, is what the row flexes — the suggestion list is
     absolutely positioned against it, so it has to be the positioned box. */
  .people-combo {
    position: relative;
    flex: 1 1 180px;
    min-width: 0;
  }
  .people-combo .form-input {
    width: 100%;
  }
  /* An overlay: a growing address book then costs the form no height at all. */
  .people-suggestions {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 20;
    margin: 2px 0 0;
    padding: 0;
    list-style: none;
    max-height: 14rem;
    overflow-y: auto;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow, 0 4px 12px rgb(0 0 0 / 0.15));
  }
  .people-suggestion {
    display: block;
    width: 100%;
    text-align: left;
    padding: var(--space-xs) var(--space-sm);
    background: none;
    border: none;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .people-suggestion.highlighted,
  .people-suggestion:hover:not(:disabled) {
    background: var(--bg-subtle);
  }
  .people-note {
    color: var(--text-muted);
    font-size: 0.85rem;
    margin: var(--space-xs) 0 0;
  }
  .people-empty,
  .people-error {
    color: var(--text-muted);
    margin: 0;
  }
  .people-error {
    color: var(--danger-text);
  }
</style>
