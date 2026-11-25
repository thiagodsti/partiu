/**
 * E2E test for the trip planner's map basemap (#/trips/:id/plan).
 *
 * Its own file because it needs WebGL, which headless Chromium only has with
 * SwiftShader, and launch options apply to a whole worker.
 */

import { test, expect } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';
import { signInPage } from './support/session';

const USER = ACCOUNTS.planOwner.username;
const PASS = ACCOUNTS.planOwner.password;

test.use({ launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } });

/* The plan map draws vector tiles through MapLibre so its labels can follow
 * the profile language. MapLibre needs two things the CSP has to allow — the
 * tile host, and a worker started from a blob: URL — and missing either leaves
 * a blank map with only a console error. The style is served locally here so
 * the test does not depend on OpenFreeMap being reachable from CI. */
test('the plan map loads its basemap without CSP violations', async ({ page }) => {
  const violations: string[] = [];
  page.on('console', (m) => {
    if (/Content Security Policy/i.test(m.text())) violations.push(m.text());
  });
  let styleRequested = false;
  await page.route('https://tiles.openfreemap.org/styles/liberty', (route) => {
    styleRequested = true;
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        version: 8,
        // A GeoJSON source is parsed in MapLibre's worker, so this is what
        // makes the test start one (with no source there is no worker, and a
        // missing worker-src would go unnoticed).
        sources: {
          pts: {
            type: 'geojson',
            data: {
              type: 'FeatureCollection',
              features: [{ type: 'Feature', properties: { name: 'X' }, geometry: { type: 'Point', coordinates: [10, 60] } }],
            },
          },
        },
        layers: [
          { id: 'bg', type: 'background', paint: { 'background-color': '#dde' } },
          { id: 'pt', type: 'circle', source: 'pts' },
        ],
      }),
    });
  });

  await signInPage(page, USER, PASS);
  const created = await page.request.post('/api/trips', {
    data: { name: 'E2E plan map', start_date: '2027-06-01', end_date: '2027-06-03' },
  });
  expect(created.ok()).toBeTruthy();
  const tripId = (await created.json()).id as string;

  await page.goto(`/#/trips/${tripId}/plan`);
  const map = page.locator('.plan-map');
  await expect(map).toBeVisible({ timeout: 15000 });

  // The vector basemap, not the raster fallback (WebGL comes from SwiftShader).
  await expect(map.locator('canvas.maplibregl-canvas')).toBeAttached({ timeout: 15000 });
  expect(styleRequested).toBe(true);
  // Give the worker time to start and parse the source.
  await page.waitForTimeout(1500);
  expect(violations).toEqual([]);
});
