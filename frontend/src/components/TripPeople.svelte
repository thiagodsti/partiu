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

  const onTrip = $derived(new Set(guests.map((g) => g.id)));

  /** Your address book minus whoever is already on this trip — the "add someone
   * you have travelled with before" list. Empty is the normal case on a first
   * trip and simply renders nothing. */
  const available = $derived(myGuests.filter((g) => !onTrip.has(g.id)));

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
      await load();
    } catch (err) {
      actionError = (err as Error).message;
    } finally {
      busyId = null;
    }
  }

  async function createAndAdd() {
    const name = newName.trim();
    if (!name || adding) return;
    actionError = null;
    adding = true;
    try {
      const { id } = await guestsApi.create(name);
      await guestsApi.addToTrip(trip.id, id);
      newName = '';
      await load();
    } catch (err) {
      actionError = (err as Error).message;
    } finally {
      adding = false;
    }
  }

  async function remove(guest: Guest) {
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

    {#if available.length > 0}
      <div class="people-available">
        <span class="people-available-label">{$t('trip_people.add_existing')}</span>
        {#each available as guest (guest.id)}
          <button
            type="button"
            class="people-chip"
            disabled={busyId === guest.id}
            onclick={() => add(guest.id)}
          >
            + {guest.name}
          </button>
        {/each}
      </div>
    {/if}

    <form
      class="people-add"
      onsubmit={(e) => {
        e.preventDefault();
        createAndAdd();
      }}
    >
      <input
        class="form-input"
        bind:value={newName}
        placeholder={$t('trip_people.add_placeholder')}
        aria-label={$t('trip_people.add_placeholder')}
      />
      <button type="submit" class="btn btn-secondary" disabled={adding || !newName.trim()}>
        {adding ? '…' : $t('trip_people.add')}
      </button>
    </form>
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
  .people-available {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-xs);
    margin-bottom: var(--space-md);
  }
  .people-available-label {
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  .people-chip {
    background: var(--bg-subtle);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 2px var(--space-sm);
    cursor: pointer;
    color: inherit;
    font: inherit;
    font-size: 0.85rem;
  }
  .people-chip:hover:not(:disabled) {
    border-color: var(--border-strong);
  }
  .people-add {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm);
  }
  .people-add .form-input {
    flex: 1 1 180px;
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
