<script lang="ts">
  import { airportsApi } from '../api/client';
  import type { Airport } from '../api/types';

  interface Props {
    value: string;
    placeholder?: string;
    required?: boolean;
    id?: string;
  }

  let {
    value = $bindable(''),
    placeholder = '',
    required = false,
    id,
  }: Props = $props();

  // Display text shown in the input
  let query = $state(value ? value : '');
  let suggestions = $state<Airport[]>([]);
  let open = $state(false);
  let activeIndex = $state(-1);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function onInput(e: Event) {
    const input = e.target as HTMLInputElement;
    query = input.value;
    // Clear the bound IATA value; it will be set when a suggestion is picked
    // or on blur for a direct 3-letter code
    value = query.trim().toUpperCase();
    activeIndex = -1;

    if (debounceTimer) clearTimeout(debounceTimer);
    if (!query.trim()) {
      suggestions = [];
      open = false;
      return;
    }
    debounceTimer = setTimeout(async () => {
      try {
        suggestions = await airportsApi.search(query);
        open = suggestions.length > 0;
      } catch {
        suggestions = [];
        open = false;
      }
    }, 250);
  }

  function select(airport: Airport) {
    value = airport.iata_code;
    query = formatSuggestion(airport);
    suggestions = [];
    open = false;
  }

  function onBlur() {
    // Delay to allow mousedown on a suggestion item to fire first
    setTimeout(() => {
      open = false;
    }, 150);
  }

  function onKeydown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, suggestions.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = Math.max(activeIndex - 1, -1);
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      select(suggestions[activeIndex]);
    } else if (e.key === 'Escape') {
      open = false;
    }
  }

  function formatSuggestion(a: Airport): string {
    const city = a.city_name ? ` — ${a.city_name}` : '';
    return `${a.iata_code}${city}`;
  }

  function formatDetail(a: Airport): string {
    const parts = [a.name];
    if (a.country_code) parts.push(a.country_code);
    return parts.join(', ');
  }
</script>

<div class="airport-combobox">
  <input
    {id}
    type="text"
    class="form-input mono"
    style="text-transform:uppercase"
    value={query}
    {placeholder}
    {required}
    maxlength="60"
    autocomplete="off"
    oninput={onInput}
    onblur={onBlur}
    onkeydown={onKeydown}
  />
  {#if open && suggestions.length > 0}
    <ul class="airport-suggestions" role="listbox">
      {#each suggestions as airport, i (airport.iata_code)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_interactive_supports_focus -->
        <li
          role="option"
          aria-selected={i === activeIndex}
          class="airport-suggestion-item"
          class:active={i === activeIndex}
          onmousedown={() => select(airport)}
        >
          <span class="suggestion-iata">{airport.iata_code}</span>
          <span class="suggestion-name">{formatDetail(airport)}</span>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .airport-combobox {
    position: relative;
    flex: 1;
  }

  .airport-combobox .form-input {
    width: 100%;
  }

  .airport-suggestions {
    position: absolute;
    top: calc(100% + 2px);
    left: 0;
    right: 0;
    z-index: 200;
    background: var(--bg-card, #ffffff);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    list-style: none;
    margin: 0;
    padding: 4px 0;
    max-height: 240px;
    overflow-y: auto;
  }

  .airport-suggestion-item {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 7px 12px;
    cursor: pointer;
    font-size: 0.875rem;
  }

  .airport-suggestion-item:hover,
  .airport-suggestion-item.active {
    background: color-mix(in srgb, var(--accent) 12%, transparent);
  }

  .suggestion-iata {
    font-family: monospace;
    font-weight: 700;
    font-size: 0.875rem;
    color: var(--accent, #6366f1);
    min-width: 36px;
  }

  .suggestion-name {
    color: var(--text);
    font-size: 0.8rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
