const fs = require('fs');
const path = require('path');
const { defineConfig } = require('@playwright/test');

// Prefer installing/running browsers from LocalAppData (avoids OneDrive/controlled-folder exec issues).
process.env.PLAYWRIGHT_BROWSERS_PATH =
  process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(process.env.LOCALAPPDATA || __dirname, 'ms-playwright');

// Some Windows setups block execution of Playwright-downloaded browser binaries; prefer system Chrome if present.
const systemChromeExeCandidates = [
  path.join(process.env['ProgramFiles'] || 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'Google', 'Chrome', 'Application', 'chrome.exe')
];
const systemChromeExe = systemChromeExeCandidates.find(p => fs.existsSync(p)) || null;

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
    screenshot: 'only-on-failure',
    ...(systemChromeExe ? { launchOptions: { executablePath: systemChromeExe } } : {})
  },
  webServer: {
    command: 'node tools/static_server.js --port 4173 --host 127.0.0.1',
    url: 'http://127.0.0.1:4173/index.html',
    timeout: 120_000,
    reuseExistingServer: true
  }
});
