import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.ts',
  // Creates every account in tests/support/accounts.ts and the seeded trip.
  // global-setup.ts lists the server flags the suite needs.
  globalSetup: './tests/global-setup.ts',
  fullyParallel: false,
  retries: 0,
  use: {
    baseURL: 'http://localhost:8000',
    headless: true,
    ...devices['Desktop Chrome'],
  },
});
