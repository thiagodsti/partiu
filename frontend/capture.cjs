const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const OUT = '/tmp/partiu-demo-frames';
const BASE = 'https://partiu-demo.teda.work';

async function shot(page, name, extra = 0) {
  if (extra > 0) await page.waitForTimeout(extra);
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
  console.log('captured', name);
}

async function duplicate(src, count) {
  const srcPath = path.join(OUT, src);
  const buf = fs.readFileSync(srcPath);
  for (let i = 0; i < count; i++) {
    const n = src.replace('.png', `_dup${String(i).padStart(2,'0')}.png`);
    fs.writeFileSync(path.join(OUT, n), buf);
  }
}

async function nav(page, hash) {
  await page.evaluate((h) => { window.location.hash = h; }, hash);
  await page.waitForTimeout(1800);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();

  // ── 1. Login ──────────────────────────────────────────────
  await page.goto(BASE, { waitUntil: 'load' });
  await page.waitForTimeout(3000);
  await shot(page, '001_login.png');
  await duplicate('001_login.png', 6);

  await page.locator('#login-username').fill('demo');
  await page.locator('#login-password').fill('demo1234');
  await shot(page, '002_login_filled.png', 300);
  await duplicate('002_login_filled.png', 4);

  await page.click('button[type="submit"]');
  await page.waitForTimeout(4000);

  // ── 2. Trips list ─────────────────────────────────────────
  await shot(page, '003_trips_list.png', 500);
  await duplicate('003_trips_list.png', 14);

  // Dump all links to find actual trip links
  const allLinks = await page.evaluate(() =>
    Array.from(document.querySelectorAll('a')).map(a => a.getAttribute('href'))
  );
  console.log('All links:', allLinks);

  // Find trip link with a numeric ID
  const tripLink = allLinks.find(h => h && /trips\/\d+/.test(h));
  console.log('Trip link found:', tripLink);

  if (tripLink) {
    const hash = tripLink.startsWith('#') ? tripLink.slice(1) : tripLink;
    await nav(page, hash);
  } else {
    // fallback: click the first card image/div that looks like a trip
    await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('a'));
      const tripLink = links.find(l => /trips\/\d+/.test(l.href));
      if (tripLink) tripLink.click();
    });
    await page.waitForTimeout(2000);
  }

  await shot(page, '010_trip_detail.png', 500);
  await duplicate('010_trip_detail.png', 14);

  await page.evaluate(() => window.scrollBy(0, 350));
  await shot(page, '011_trip_scroll.png', 400);
  await duplicate('011_trip_scroll.png', 10);

  await page.evaluate(() => window.scrollBy(0, 350));
  await shot(page, '012_trip_scroll2.png', 400);
  await duplicate('012_trip_scroll2.png', 8);

  // ── 3. Flight detail ──────────────────────────────────────
  await page.evaluate(() => window.scrollTo(0, 0));
  const flightLinks = await page.evaluate(() =>
    Array.from(document.querySelectorAll('a')).map(a => a.getAttribute('href'))
  );
  console.log('Flight page links:', flightLinks);

  const flightLink = flightLinks.find(h => h && /flights?\//.test(h) && !h.endsWith('/flights'));
  console.log('Flight link found:', flightLink);

  if (flightLink) {
    const hash = flightLink.startsWith('#') ? flightLink.slice(1) : flightLink;
    await nav(page, hash);
    await shot(page, '020_flight_detail.png', 500);
    await duplicate('020_flight_detail.png', 14);

    await page.evaluate(() => window.scrollBy(0, 400));
    await shot(page, '021_flight_scroll.png', 400);
    await duplicate('021_flight_scroll.png', 10);
  } else {
    console.log('No flight link found');
    await shot(page, '020_flight_detail.png', 200);
    await duplicate('020_flight_detail.png', 4);
  }

  // ── 4. Stats page ─────────────────────────────────────────
  await nav(page, '/stats');
  await shot(page, '030_stats.png', 500);
  await duplicate('030_stats.png', 14);

  await page.evaluate(() => window.scrollBy(0, 500));
  await shot(page, '031_stats_scroll.png', 400);
  await duplicate('031_stats_scroll.png', 12);

  // ── 5. History page ───────────────────────────────────────
  await nav(page, '/history');
  await shot(page, '040_history.png', 500);
  await duplicate('040_history.png', 12);

  // ── 6. Notifications ──────────────────────────────────────
  await nav(page, '/notifications');
  await shot(page, '050_notifications.png', 500);
  await duplicate('050_notifications.png', 10);

  // ── 7. Settings page ──────────────────────────────────────
  await nav(page, '/settings');
  await shot(page, '060_settings.png', 500);
  await duplicate('060_settings.png', 12);

  await page.evaluate(() => window.scrollBy(0, 400));
  await shot(page, '061_settings_scroll.png', 400);
  await duplicate('061_settings_scroll.png', 8);

  // ── 8. Back to trips list (ending) ────────────────────────
  await nav(page, '/trips');
  await shot(page, '070_trips_final.png', 500);
  await duplicate('070_trips_final.png', 12);

  await browser.close();
  console.log('Done! Frames in', OUT);
})();
