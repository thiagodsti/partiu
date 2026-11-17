import process from 'node:process';
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.ts',
  // Creates every account in tests/support/accounts.ts and the seeded trip.
  // global-setup.ts lists the server flags the suite needs.
  globalSetup: './tests/global-setup.ts',
  fullyParallel: false,
  // CI's default is the dot reporter, which prints a ° per skipped test and no
  // names — a skip there could not be told apart from another. List them, and
  // keep an HTML report for the artifact the workflow uploads on failure.
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  retries: 0,
  use: {
    // Global setup provisions accounts on this same server, so a spec pointed
    // elsewhere with E2E_BASE_URL finds them there too.
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000',
    headless: true,
    ...devices['Desktop Chrome'],
  },
});
