/**
 * E2E tests for "Suggest ideas" in the planner.
 *
 * The AI and the map check run on the server and are covered by the backend
 * tests (backend/tests/suggestions/); a CI server has no AI provider, so here
 * the two suggestion endpoints are answered in the browser. What this checks
 * is the part only a browser can: the buttons appear only when the server
 * offers the feature, a request carries what was picked, and "+" puts the
 * place on the plan — through the planner's real API — with its pin and note.
 */

import { test, expect, type Page } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';
import { signInPage } from './support/session';

// The app's service worker answers /api/* itself, out of page.route's sight.
test.use({ serviceWorkers: 'block' });

const USER = ACCOUNTS.planOwner.username;
const PASS = ACCOUNTS.planOwner.password;

const THUMB = 'https://upload.wikimedia.org/wikipedia/commons/thumb/x/TimeOut.jpg/320px-TimeOut.jpg';
// A 1×1 PNG, so no test reaches Wikimedia.
const PIXEL = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
);

const SUGGESTIONS = {
  city: 'Lisbon',
  day: null,
  unverified: 0,
  suggestions: [
    {
      title: 'Time Out Market',
      why: 'Many Lisbon kitchens under one roof.',
      category: 'food',
      best_time: 'evening',
      // Placed by its Wikipedia article: no map lookup on add.
      on_wikipedia: true,
      image_url: THUMB,
      image_page: 'https://en.wikipedia.org/wiki/Time_Out_Market_Lisboa',
      lat: 38.7069,
      lon: -9.1459,
    },
  ],
};

// No article: the map is asked only when it is added.
const TASCA = {
  title: 'Tasca do Chico',
  why: 'Fado in a tiny room.',
  category: 'nightlife',
  best_time: 'evening',
  on_wikipedia: false,
  image_url: null,
  image_page: null,
  lat: null,
  lon: null,
};

async function offerSuggestions(page: Page, available: boolean) {
  await page.route('https://upload.wikimedia.org/**', (route) =>
    route.fulfill({ body: PIXEL, contentType: 'image/png' }),
  );
  await page.route('**/api/suggestions/status', (route) =>
    route.fulfill({ json: { available, use_history: false, daily_limit: 40, used_today: 0 } }),
  );
}

async function tripWithLisbon(page: Page): Promise<string> {
  const created = await page.request.post('/api/trips', {
    data: { name: 'E2E suggestions', planned_start_date: '2027-05-10', planned_end_date: '2027-05-12' },
  });
  expect(created.ok()).toBeTruthy();
  const tripId = (await created.json()).id as string;
  const stop = await page.request.post(`/api/trips/${tripId}/plan/stops`, {
    data: { name: 'Lisbon', start_date: '2027-05-10', end_date: '2027-05-12' },
  });
  expect(stop.ok()).toBeTruthy();
  return tripId;
}

test('no suggestion buttons when the server has no AI', async ({ page }) => {
  await signInPage(page, USER, PASS);
  await offerSuggestions(page, false);
  const tripId = await tripWithLisbon(page);
  try {
    await page.goto(`/#/trips/${tripId}/plan`);
    await expect(page.locator('.stop-chip', { hasText: 'Lisbon' })).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('suggest-stop')).toHaveCount(0);
    await expect(page.getByTestId('suggest-day')).toHaveCount(0);
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test('suggestions for a city are asked for and added to the plan', async ({ page }) => {
  await signInPage(page, USER, PASS);
  await offerSuggestions(page, true);
  let sent: Record<string, unknown> | null = null;
  await page.route('**/api/trips/*/plan/suggestions', async (route) => {
    sent = route.request().postDataJSON();
    await route.fulfill({ json: SUGGESTIONS });
  });
  const tripId = await tripWithLisbon(page);
  try {
    await page.goto(`/#/trips/${tripId}/plan`);
    await page.getByTestId('suggest-stop').first().click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Lisbon');
    await dialog.locator('.sg-chip', { hasText: /Food|Comida/ }).click();
    await dialog.locator('.sg-ask input').fill('rainy day');
    await dialog.locator('.sg-ask button[type=submit]').click();

    await expect(dialog.locator('.sg-card')).toHaveCount(1);
    await expect(dialog.locator('.sg-card')).toContainText('Time Out Market');
    expect(sent).toMatchObject({ interests: ['food'], wish: 'rainy day', date: null, exclude: [] });
    expect((sent as unknown as { stop_id: string }).stop_id).toBeTruthy();

    await dialog.locator('.sg-add').click();
    await expect(dialog.locator('.sg-add')).toHaveText('✓');

    // On the plan for real: an unscheduled idea, with its pin and the reason.
    await expect
      .poll(async () => {
        const plan = await (await page.request.get(`/api/trips/${tripId}/plan`)).json();
        return plan.items.find((i: { title: string }) => i.title === 'Time Out Market') ?? null;
      })
      .toMatchObject({
        date: null,
        status: 'idea',
        place_name: 'Time Out Market',
        lat: 38.7069,
        lon: -9.1459,
        notes: 'Many Lisbon kitchens under one roof.',
        // The card's photo stays with the item.
        image_url: THUMB,
        image_page: 'https://en.wikipedia.org/wiki/Time_Out_Market_Lisboa',
      });

    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    const added = page.locator('.panel .item', { hasText: 'Time Out Market' });
    await expect(added).toBeVisible();
    await expect(added.locator('img.item-photo')).toHaveAttribute('src', THUMB);

    // Reopened, the panel shows the same list without asking again.
    const asked = sent;
    sent = null;
    await page.getByTestId('suggest-stop').first().click();
    await expect(page.getByRole('dialog').locator('.sg-card')).toContainText('Time Out Market');
    expect(sent).toBeNull();
    expect(asked).not.toBeNull();
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test('suggestions asked from a day land on that day', async ({ page }) => {
  await signInPage(page, USER, PASS);
  await offerSuggestions(page, true);
  await page.route('**/api/trips/*/plan/suggestions', (route) =>
    route.fulfill({ json: { ...SUGGESTIONS, day: '2027-05-11' } }),
  );
  const tripId = await tripWithLisbon(page);
  try {
    await page.goto(`/#/trips/${tripId}/plan`);
    const secondDay = page.locator('.items-cell').nth(1);
    await secondDay.getByTestId('suggest-day').click();
    const dialog = page.getByRole('dialog');
    await dialog.locator('.sg-ask button[type=submit]').click();
    await dialog.locator('.sg-add').click();
    await expect(dialog.locator('.sg-add')).toHaveText('✓');
    await expect
      .poll(async () => {
        const plan = await (await page.request.get(`/api/trips/${tripId}/plan`)).json();
        return plan.items.find((i: { title: string }) => i.title === 'Time Out Market')?.date;
      })
      .toBe('2027-05-11');
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test('a place without an article is looked up on the map when it is added', async ({ page }) => {
  await signInPage(page, USER, PASS);
  await offerSuggestions(page, true);
  await page.route('**/api/trips/*/plan/suggestions', (route) =>
    route.fulfill({ json: { city: 'Lisbon', day: null, unverified: 0, suggestions: [TASCA] } }),
  );
  let located: Record<string, unknown> | null = null;
  await page.route('**/api/trips/*/plan/suggestions/locate', async (route) => {
    located = route.request().postDataJSON();
    await route.fulfill({
      json: { place_name: 'Tasca do Chico', local_name: null, address: 'Lisboa', lat: 38.7115, lon: -9.144 },
    });
  });
  const tripId = await tripWithLisbon(page);
  try {
    await page.goto(`/#/trips/${tripId}/plan`);
    await page.getByTestId('suggest-stop').first().click();
    const dialog = page.getByRole('dialog');
    await dialog.locator('.sg-ask button[type=submit]').click();
    await dialog.locator('.sg-add').click();
    await expect(dialog.locator('.sg-add')).toHaveText('✓');
    expect(located).toMatchObject({ name: 'Tasca do Chico' });
    await expect
      .poll(async () => {
        const plan = await (await page.request.get(`/api/trips/${tripId}/plan`)).json();
        return plan.items.find((i: { title: string }) => i.title === 'Tasca do Chico') ?? null;
      })
      .toMatchObject({ place_name: 'Tasca do Chico', lat: 38.7115, lon: -9.144 });
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test('"arrange my day" shows a proposal and applies it only when accepted', async ({ page }) => {
  await signInPage(page, USER, PASS);
  await offerSuggestions(page, true);
  const tripId = await tripWithLisbon(page);
  const ids: string[] = [];
  for (const title of ['Dinner at Tasca', 'Belém Tower']) {
    const r = await page.request.post(`/api/trips/${tripId}/plan/items`, { data: { title, date: '2027-05-11' } });
    ids.push((await r.json()).id);
  }
  const [dinner, tower] = ids;
  let sent: Record<string, unknown> | null = null;
  await page.route('**/api/trips/*/plan/arrange', async (route) => {
    sent = route.request().postDataJSON();
    await route.fulfill({
      json: {
        day: '2027-05-11',
        tip: 'Go to Belém early.',
        items: [
          { id: tower, title: 'Belém Tower', time: '09:30', current_time: null, fixed: false },
          { id: dinner, title: 'Dinner at Tasca', time: '20:00', current_time: null, fixed: false },
        ],
      },
    });
  });
  try {
    await page.goto(`/#/trips/${tripId}/plan`);
    const secondDay = page.locator('.items-cell').nth(1);
    await secondDay.getByTestId('arrange-day').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Go to Belém early.');
    expect(sent).toMatchObject({ date: '2027-05-11' });

    // Cancelling writes nothing.
    await dialog.getByRole('button', { name: /Cancel|Cancelar/ }).click();
    let plan = await (await page.request.get(`/api/trips/${tripId}/plan`)).json();
    expect(plan.items.every((i: { time: string | null }) => i.time === null)).toBe(true);

    await secondDay.getByTestId('arrange-day').click();
    await page.getByRole('dialog').getByRole('button', { name: /Apply|Aplicar/ }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect
      .poll(async () => {
        plan = await (await page.request.get(`/api/trips/${tripId}/plan`)).json();
        return plan.items
          .filter((i: { date: string }) => i.date === '2027-05-11')
          .map((i: { title: string; time: string }) => `${i.time} ${i.title}`);
      })
      .toEqual(['09:30 Belém Tower', '20:00 Dinner at Tasca']);
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test('suggestions are on a map in the panel, and a card can be picked out on it', async ({ page }) => {
  await signInPage(page, USER, PASS);
  await offerSuggestions(page, true);
  await page.route('**/api/trips/*/plan/suggestions', (route) =>
    route.fulfill({
      json: {
        ...SUGGESTIONS,
        suggestions: [
          ...SUGGESTIONS.suggestions,
          { ...SUGGESTIONS.suggestions[0], title: 'Belém Tower', lat: 38.6916, lon: -9.216, image_url: null },
          TASCA,
        ],
      },
    }),
  );
  const tripId = await tripWithLisbon(page);
  try {
    await page.goto(`/#/trips/${tripId}/plan`);
    await page.getByTestId('suggest-stop').first().click();
    const dialog = page.getByRole('dialog');
    await dialog.locator('.sg-ask button[type=submit]').click();
    // Two placed cards → two numbered pins; the one without a position has neither.
    await expect(dialog.locator('.sg-map .plan-pin.item')).toHaveCount(2);
    await expect(dialog.locator('.sg-num')).toHaveText(['1', '2']);
    await dialog.locator('.sg-card', { hasText: 'Belém Tower' }).locator('.sg-show').click();
    await expect(dialog.locator('.sg-card.selected')).toContainText('Belém Tower');
    await expect(dialog.locator('.sg-map .plan-pin.highlight')).toHaveText('2');
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test("an item's 🔎 zooms the plan map to it", async ({ page }) => {
  await signInPage(page, USER, PASS);
  await offerSuggestions(page, false);
  const tripId = await tripWithLisbon(page);
  await page.request.post(`/api/trips/${tripId}/plan/items`, {
    data: { title: 'Belém Tower', date: '2027-05-11', place_name: 'Belém Tower', lat: 38.6916, lon: -9.216 },
  });
  try {
    await page.goto(`/#/trips/${tripId}/plan`);
    await page.locator('.items-cell').nth(1).getByTestId('item-locate').click();
    await expect(page.locator('.map-section')).toContainText('📍 Belém Tower');
    await expect(page.locator('.map-section .plan-pin.highlight')).toHaveCount(1);
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test('an Apply that fails half-way shows what the server holds, and says so', async ({ page }) => {
  await signInPage(page, USER, PASS);
  await offerSuggestions(page, true);
  const tripId = await tripWithLisbon(page);
  const ids: string[] = [];
  for (const title of ['Dinner at Tasca', 'Belém Tower']) {
    const r = await page.request.post(`/api/trips/${tripId}/plan/items`, { data: { title, date: '2027-05-11' } });
    ids.push((await r.json()).id);
  }
  const [dinner, tower] = ids;
  await page.route('**/api/trips/*/plan/arrange', (route) =>
    route.fulfill({
      json: {
        day: '2027-05-11',
        tip: null,
        items: [
          { id: tower, title: 'Belém Tower', time: '09:30', current_time: null, fixed: false },
          { id: dinner, title: 'Dinner at Tasca', time: '20:00', current_time: null, fixed: false },
        ],
      },
    }),
  );
  // The dinner's write fails; the tower's lands.
  await page.route(`**/api/trips/*/plan/items/${dinner}`, (route) =>
    route.request().method() === 'PATCH' ? route.fulfill({ status: 500, json: { detail: 'boom' } }) : route.continue(),
  );
  try {
    await page.goto(`/#/trips/${tripId}/plan`);
    const secondDay = page.locator('.items-cell').nth(1);
    await secondDay.getByTestId('arrange-day').click();
    await page.getByRole('dialog').getByRole('button', { name: /Apply|Aplicar/ }).click();
    await expect(page.locator('.arrange-error')).toBeVisible();
    // The board matches the server: the tower has its time, the dinner none.
    await expect(secondDay.locator('.item', { hasText: 'Belém Tower' }).locator('.item-time')).toHaveText('09:30');
    await expect(secondDay.locator('.item', { hasText: 'Dinner at Tasca' }).locator('.item-time')).toHaveCount(0);
    // Focus is back on the day's Arrange button.
    await expect(secondDay.getByTestId('arrange-day')).toBeFocused();
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});
