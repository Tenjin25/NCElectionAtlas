/**
 * Capture README screenshots with the current DRA palette.
 * Usage: node tools/capture_readme_screenshots.js
 * Expects static server on SMOKE_PORT (default 4173).
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const HOST = '127.0.0.1';
const PORT = Number(process.env.SMOKE_PORT || 4173);
const URL = `http://${HOST}:${PORT}/index.html?v=readme-shots-${Date.now()}`;
const outDir = path.resolve(__dirname, '..', 'Screenshots');
const APP_READY_TIMEOUT = 180_000;

const systemChromeExeCandidates = [
  path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'Google', 'Chrome', 'Application', 'chrome.exe')
];
const systemChromeExe = systemChromeExeCandidates.find((p) => fs.existsSync(p)) || null;

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForAtlasReady(page) {
  await page.waitForSelector('#map .mapboxgl-canvas', { timeout: APP_READY_TIMEOUT });
  await page.waitForSelector('#contestSelect', { timeout: APP_READY_TIMEOUT });
  await page.waitForFunction(() => {
    const sel = document.getElementById('contestSelect');
    return !!(sel && Array.from(sel.options || []).some((o) => (o?.value || '').trim()));
  }, { timeout: APP_READY_TIMEOUT });
}

async function selectContest(page, contestValue) {
  await page.selectOption('#contestSelect', contestValue);
  await page.waitForFunction(
    (v) => (
      document.getElementById('contestSelect')?.value === v &&
      typeof lastCompletedContestSelection !== 'undefined' &&
      lastCompletedContestSelection === v
    ),
    contestValue,
    { timeout: APP_READY_TIMEOUT }
  );
  await wait(1500);
}

async function setView(page, testId) {
  await page.locator(`[data-testid="${testId}"]`).click();
  await wait(900);
}

async function prepareCleanUi(page) {
  await page.evaluate(() => {
    document.body.classList.add('dra-palette');
    const help = document.getElementById('help-modal');
    if (help) help.style.display = 'none';
    const helpBackdrop = document.getElementById('help-backdrop');
    if (helpBackdrop) helpBackdrop.style.display = 'none';
    try {
      localStorage.setItem('nc-atlas-partisan-palette-v4', 'dra');
    } catch (_) {}
  });
}

async function shot(page, filename) {
  const dest = path.join(outDir, filename);
  await page.screenshot({ path: dest, type: 'png' });
  console.log(`wrote ${dest}`);
}

async function main() {
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    ...(systemChromeExe ? { executablePath: systemChromeExe } : {})
  });

  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 }
    });
    page.setDefaultTimeout(APP_READY_TIMEOUT);
    page.on('console', (msg) => {
      if (msg.type() === 'error') console.log(`[page:${msg.type()}] ${msg.text()}`);
    });

    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await waitForAtlasReady(page);
    await prepareCleanUi(page);

    // 1) Counties — 2024 Presidential
    await setView(page, 'view-counties');
    await selectContest(page, 'president_2024');
    await wait(1200);
    await shot(page, 'AtlasLatest2024PresCounty.png');

    // 2) Congress — 2020 Presidential
    await setView(page, 'view-congress');
    await selectContest(page, 'president_2020');
    await wait(1800);
    await shot(page, 'Latest2020PresCongress.png');

    // 3) State House — 2024 Presidential
    await setView(page, 'view-state-house');
    await selectContest(page, 'president_2024');
    await wait(1800);
    await shot(page, '2024StateHousePres.png');

    // 4) State Senate — 2022 US Senate
    await setView(page, 'view-state-senate');
    await selectContest(page, 'us_senate_2022');
    await wait(1800);
    await shot(page, '2022USSenStatSen.png');

    // 5) Precinct zoom — Forsyth / Triad
    await setView(page, 'view-counties');
    await selectContest(page, 'president_2024');
    const precinctBtn = page.locator('button[aria-label="Toggle precinct overlay"]');
    if (await precinctBtn.count()) {
      const pressed = await precinctBtn.first().getAttribute('aria-pressed');
      if (pressed !== 'true') await precinctBtn.first().click();
      await wait(800);
    }
    const triadBtn = page.locator('button[data-region-jump="triad"], button[aria-label="Jump to triad"]');
    if (await triadBtn.count()) {
      await triadBtn.first().click();
      await wait(2500);
    }
    const flyInput = page.locator('#desktop-fly-search');
    if (await flyInput.count()) {
      await flyInput.fill('Forsyth');
      await flyInput.press('Enter');
      await wait(2800);
    }
    await shot(page, 'ForsythPrecinctZoom.png');

    console.log('done');
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
