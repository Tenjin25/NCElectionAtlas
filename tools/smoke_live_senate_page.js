const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const URL = process.env.SMOKE_URL || 'https://tenjin25.github.io/NCElectionAtlas/';

const systemChromeExeCandidates = [
  path.join(process.env['ProgramFiles'] || 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'Google', 'Chrome', 'Application', 'chrome.exe')
];
const systemChromeExe = systemChromeExeCandidates.find((p) => fs.existsSync(p)) || null;

async function main() {
  const browser = await chromium.launch({
    headless: true,
    ...(systemChromeExe ? { executablePath: systemChromeExe } : {})
  });
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(240000);
    page.on('console', (msg) => console.log(`[page:${msg.type()}] ${msg.text()}`));
    page.on('pageerror', (err) => console.error('[pageerror]', err && err.stack ? err.stack : err));

    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#contestSelect');
    await page.waitForFunction(() => {
      const sel = document.getElementById('contestSelect');
      return !!(sel && Array.from(sel.options || []).some((opt) => String(opt.value || '').trim() === 'us_senate_model_2026'));
    });
    await page.selectOption('#contestSelect', 'us_senate_model_2026');
    await page.waitForFunction(() => {
      const leadText = document.querySelector('.statewide-call')?.textContent || '';
      return /Whatley|Cooper|R\+|D\+/.test(leadText);
    }, { timeout: 240000 });

    const result = await page.evaluate(async () => {
      const pickStat = (label) => {
        const stats = Array.from(document.querySelectorAll('.statewide-stat'));
        for (const stat of stats) {
          const span = stat.querySelector('span');
          const strong = stat.querySelector('strong');
          if (!span || !strong) continue;
          if ((span.textContent || '').trim().toLowerCase() === label.toLowerCase()) {
            return (strong.textContent || '').trim();
          }
        }
        return '';
      };
      const rows = await loadContestSlice('us_senate_model', 2026);
      const totals = (rows || []).reduce((acc, row) => {
        acc.dem += Number(row?.us_senate_model_dem || 0);
        acc.rep += Number(row?.us_senate_model_rep || 0);
        acc.other += Number(row?.us_senate_model_other || 0);
        acc.total += Number(row?.us_senate_model_total || 0);
        return acc;
      }, { dem: 0, rep: 0, other: 0, total: 0 });
      return {
        buildId: window.__ATLAS_BUILD__ || '',
        location: window.location.href,
        scenarioSwingPct: window.scenarioSwingPct,
        scenarioScope: window.scenarioScope,
        contestValue: document.getElementById('contestSelect')?.value || '',
        statewideCall: document.querySelector('.statewide-call')?.textContent?.trim() || '',
        syntheticTotal: pickStat('Synthetic total'),
        modeledMargin: pickStat('Modeled margin'),
        voteTotal: document.getElementById('vote-total')?.textContent?.trim() || '',
        leadText: document.getElementById('vote-lead')?.textContent?.trim() || '',
        rowTotals: totals,
        localStorageKeys: Object.keys(window.localStorage || {}).sort(),
        search: window.location.search || ''
      };
    });

    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exitCode = 1;
});
