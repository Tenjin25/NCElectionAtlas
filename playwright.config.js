const path = require('path');
const { defineConfig } = require('@playwright/test');

process.env.PLAYWRIGHT_BROWSERS_PATH =
  process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(__dirname, '.playwright-browsers');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 120_000,
  expect: {
    timeout: 20_000
  },
  fullyParallel: false,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    headless: true,
    acceptDownloads: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: {
    command: 'py -m http.server 4173 --bind 127.0.0.1',
    url: 'http://127.0.0.1:4173/index.html',
    timeout: 120_000,
    reuseExistingServer: true
  }
});
