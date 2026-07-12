const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');

const HOST = '127.0.0.1';
const PORT = Number(process.env.SMOKE_PORT || 4190);
const URL = `http://${HOST}:${PORT}/index.html`;
const overrideDemNomineeStrength = process.env.DEM_NOMINEE_STRENGTH;
const overrideRepNomineeStrength = process.env.REP_NOMINEE_STRENGTH;
const overrideBlendWeight = process.env.MODEL_BLEND_WEIGHT;
const overrideRecenterStrength = process.env.MODEL_RECENTER_STRENGTH;
const overrideCandidateBonusWeight = process.env.MODEL_CANDIDATE_BONUS_WEIGHT;

const systemChromeExeCandidates = [
  path.join(process.env['ProgramFiles'] || 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'Google', 'Chrome', 'Application', 'chrome.exe')
];
const systemChromeExe = systemChromeExeCandidates.find((p) => fs.existsSync(p)) || null;

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  const server = spawn(
    process.execPath,
    [path.join(__dirname, 'static_server.js'), '--port', String(PORT), '--host', HOST],
    {
      cwd: path.resolve(__dirname, '..'),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true
    }
  );

  let serverClosed = false;
  server.on('exit', () => {
    serverClosed = true;
  });
  server.stdout.on('data', (chunk) => process.stdout.write(String(chunk)));
  server.stderr.on('data', (chunk) => process.stderr.write(String(chunk)));

  const browser = await chromium.launch({
    headless: true,
    ...(systemChromeExe ? { executablePath: systemChromeExe } : {})
  });

  try {
    await wait(1500);
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
    if (
      overrideDemNomineeStrength !== undefined ||
      overrideRepNomineeStrength !== undefined ||
      overrideBlendWeight !== undefined ||
      overrideRecenterStrength !== undefined ||
      overrideCandidateBonusWeight !== undefined
    ) {
      await page.evaluate((overrides) => {
        const def = MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026;
        if (!def) return;
        if (overrides.dem !== null && overrides.dem !== undefined && overrides.dem !== '') def.demNomineeStrengthPts = Number(overrides.dem);
        if (overrides.rep !== null && overrides.rep !== undefined && overrides.rep !== '') def.repNomineeStrengthPts = Number(overrides.rep);
        if (overrides.blend !== null && overrides.blend !== undefined && overrides.blend !== '') def.blendWeight = Number(overrides.blend);
        if (overrides.recenter !== null && overrides.recenter !== undefined && overrides.recenter !== '') def.statewideRecenterStrength = Number(overrides.recenter);
        if (overrides.bonusWeight !== null && overrides.bonusWeight !== undefined && overrides.bonusWeight !== '') def.candidateBonusWeight = Number(overrides.bonusWeight);
        try { modeledCountyOutputCache?.clear?.(); } catch (_) {}
        try { modeledCountyOutputInflight?.clear?.(); } catch (_) {}
        try { modeledDistrictOutputCache?.clear?.(); } catch (_) {}
        try { modeledDistrictOutputInflight?.clear?.(); } catch (_) {}
        try { modeledSenateInsightsCache?.clear?.(); } catch (_) {}
      }, {
        dem: overrideDemNomineeStrength ?? null,
        rep: overrideRepNomineeStrength ?? null,
        blend: overrideBlendWeight ?? null,
        recenter: overrideRecenterStrength ?? null,
        bonusWeight: overrideCandidateBonusWeight ?? null
      });
    }
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
        contestValue: document.getElementById('contestSelect')?.value || '',
        statewideCall: document.querySelector('.statewide-call')?.textContent?.trim() || '',
        syntheticTotal: pickStat('Synthetic total'),
        modeledMargin: pickStat('Modeled margin'),
        voteTotal: document.getElementById('vote-total')?.textContent?.trim() || '',
        leadText: document.getElementById('vote-lead')?.textContent?.trim() || '',
        rowTotals: totals,
        search: window.location.search || '',
        demNomineeStrengthPts: Number(MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026?.demNomineeStrengthPts),
        repNomineeStrengthPts: Number(MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026?.repNomineeStrengthPts),
        blendWeight: Number(MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026?.blendWeight),
        statewideRecenterStrength: Number(MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026?.statewideRecenterStrength),
        candidateBonusWeight: Number(MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026?.candidateBonusWeight)
      };
    });

    console.log(JSON.stringify(result, null, 2));
  } finally {
    try { await browser.close(); } catch (_) {}
    if (!serverClosed) {
      try { server.kill(); } catch (_) {}
    }
  }
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exitCode = 1;
});
