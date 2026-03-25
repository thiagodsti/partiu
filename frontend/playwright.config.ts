import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  retries: 0,
  use: {
    baseURL: 'http://localhost:8000',
    headless: true,
    ...devices['Desktop Chrome'],
  },
});
