const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');

const HOST = '127.0.0.1';
const PORT = Number(process.env.SMOKE_PORT || 4173);
const URL = `http://${HOST}:${PORT}/index.html`;
const overrideDemNomineeStrength = process.env.DEM_NOMINEE_STRENGTH;
const overrideRepNomineeStrength = process.env.REP_NOMINEE_STRENGTH;
const overrideBlendWeight = process.env.MODEL_BLEND_WEIGHT;

const systemChromeExeCandidates = [
  path.join(process.env['ProgramFiles'] || 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'Google', 'Chrome', 'Application', 'chrome.exe')
];
const systemChromeExe = systemChromeExeCandidates.find((p) => fs.existsSync(p)) || null;

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForServerReady() {
  for (let i = 0; i < 120; i += 1) {
    try {
      const res = await fetch(URL, { cache: 'no-store' });
      if (res.ok) return;
    } catch (_) {}
    await wait(500);
  }
  throw new Error(`Timed out waiting for ${URL}`);
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

  server.stdout.on('data', (chunk) => {
    process.stdout.write(String(chunk));
  });
  server.stderr.on('data', (chunk) => {
    process.stderr.write(String(chunk));
  });

  let browser;
  try {
    await waitForServerReady();
    browser = await chromium.launch({
      headless: true,
      ...(systemChromeExe ? { executablePath: systemChromeExe } : {})
    });
    const page = await browser.newPage();
    await page.addInitScript(() => {
      const noop = () => {};
      const chain = () => fakeMap;
      class FakePopup {
        setLngLat() { return this; }
        setHTML() { return this; }
        setDOMContent() { return this; }
        addTo() { return this; }
        remove() { return this; }
        on() { return this; }
      }
      class FakeMarker {
        setLngLat() { return this; }
        addTo() { return this; }
        remove() { return this; }
        getElement() { return document.createElement('div'); }
      }
      class FakeLngLatBounds {
        extend() { return this; }
      }
      const fakeMap = {
        on(event, cb) {
          if (event === 'load' || event === 'style.load' || event === 'idle') {
            setTimeout(() => { try { cb(); } catch (_) {} }, 0);
          }
          return this;
        },
        once(event, cb) { return this.on(event, cb); },
        off() { return this; },
        addControl: chain,
        resize: chain,
        addSource: chain,
        removeSource: chain,
        getSource() { return null; },
        addLayer: chain,
        moveLayer: chain,
        removeLayer: chain,
        getLayer() { return null; },
        setPaintProperty: chain,
        getPaintProperty() { return null; },
        setLayoutProperty: chain,
        getLayoutProperty() { return null; },
        setFilter: chain,
        getFilter() { return null; },
        fitBounds: chain,
        flyTo: chain,
        easeTo: chain,
        jumpTo: chain,
        project() { return { x: 0, y: 0 }; },
        unproject() { return { lng: 0, lat: 0 }; },
        queryRenderedFeatures() { return []; },
        querySourceFeatures() { return []; },
        getCenter() { return { lng: -79.0, lat: 35.5 }; },
        getZoom() { return 6; },
        getBearing() { return 0; },
        getPitch() { return 0; },
        setFeatureState: chain,
        removeFeatureState: chain,
        loaded() { return true; },
        isStyleLoaded() { return true; },
        getCanvas() { return document.createElement('canvas'); },
        getCanvasContainer() {
          const el = document.createElement('div');
          el.className = 'mapboxgl-canvas-container mapboxgl-interactive';
          return el;
        },
        getContainer() {
          return document.getElementById('map') || document.body;
        }
      };
      window.mapboxgl = {
        accessToken: '',
        setTelemetryEnabled: noop,
        Map: function Map() { return fakeMap; },
        Popup: FakePopup,
        Marker: FakeMarker,
        NavigationControl: function NavigationControl() {},
        LngLatBounds: FakeLngLatBounds
      };
      window.turf = window.turf || {};
      window.Papa = window.Papa || {
        parse(_input, opts = {}) {
          const result = { data: [], errors: [], meta: {} };
          if (typeof opts.complete === 'function') {
            setTimeout(() => opts.complete(result), 0);
            return undefined;
          }
          if (typeof opts.chunk === 'function') {
            setTimeout(() => {
              try { opts.chunk(result); } catch (_) {}
              if (typeof opts.complete === 'function') opts.complete(result);
            }, 0);
            return undefined;
          }
          return result;
        }
      };
    });
    page.on('console', (msg) => {
      const type = msg.type ? msg.type() : 'log';
      console.log(`[page:${type}] ${msg.text()}`);
    });
    page.on('pageerror', (err) => {
      console.error('[pageerror]', err && err.stack ? err.stack : err);
    });
    page.setDefaultTimeout(180000);
    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#contestSelect');
    await page.waitForFunction(() => {
      const sel = document.getElementById('contestSelect');
      return !!(sel && Array.from(sel.options || []).some((opt) => String(opt.value || '').trim() === 'us_senate_model_2026'));
    });
    if (overrideDemNomineeStrength !== undefined || overrideRepNomineeStrength !== undefined) {
      await page.evaluate(({ demOverride, repOverride }) => {
        const def = MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026;
        if (!def) return;
        if (demOverride !== null && demOverride !== undefined && demOverride !== '') {
          def.demNomineeStrengthPts = Number(demOverride);
        }
        if (repOverride !== null && repOverride !== undefined && repOverride !== '') {
          def.repNomineeStrengthPts = Number(repOverride);
        }
        if (blendOverride !== null && blendOverride !== undefined && blendOverride !== '') {
          def.blendWeight = Number(blendOverride);
        }
        try { modeledCountyOutputCache?.clear?.(); } catch (_) {}
        try { modeledCountyOutputInflight?.clear?.(); } catch (_) {}
        try { modeledDistrictOutputCache?.clear?.(); } catch (_) {}
        try { modeledDistrictOutputInflight?.clear?.(); } catch (_) {}
        try { modeledSenateInsightsCache?.clear?.(); } catch (_) {}
      }, {
        demOverride: overrideDemNomineeStrength ?? null,
        repOverride: overrideRepNomineeStrength ?? null,
        blendOverride: overrideBlendWeight ?? null
      });
    }
    await page.evaluate(async () => {
      const sel = document.getElementById('contestSelect');
      if (sel) sel.value = 'us_senate_model_2026';
      if (typeof applyContest === 'function') {
        await applyContest('us_senate_model_2026', { force: true, selectionSeq: 999999 });
      }
    });
    await page.waitForFunction(() => document.getElementById('contestSelect')?.value === 'us_senate_model_2026');

    const result = await page.evaluate(async () => {
      const modeledDef = MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026;
      const rows = modeledDef && typeof buildModeledContestSliceRows === 'function'
        ? await buildModeledContestSliceRows(modeledDef)
        : await loadContestSlice('us_senate_model', 2026);
      const totals = (rows || []).reduce((acc, row) => {
        acc.dem += Number(row?.us_senate_model_dem || 0);
        acc.rep += Number(row?.us_senate_model_rep || 0);
        acc.other += Number(row?.us_senate_model_other || 0);
        acc.total += Number(row?.us_senate_model_total || 0);
        return acc;
      }, { dem: 0, rep: 0, other: 0, total: 0 });
      const marginPct = typeof marginPctDisplayValue === 'function'
        ? marginPctDisplayValue(totals.rep, totals.dem, totals.total)
        : ((totals.rep - totals.dem) / totals.total) * 100;
      const voteTotalText = document.getElementById('vote-total')?.textContent?.trim() || '';
      const winnerText = document.getElementById('county-winner')?.textContent?.trim() || '';
      const leadText = document.getElementById('county-margin')?.textContent?.trim() || '';
      return {
        totals,
        marginPct,
        voteTotalText,
        winnerText,
        leadText,
        buildId: window.__ATLAS_BUILD__ || null,
        statewideCallText: document.querySelector('.statewide-call')?.textContent?.trim() || '',
        statewideMarginText: Array.from(document.querySelectorAll('.statewide-stat strong')).map((el) => el.textContent?.trim() || ''),
        baselineState: window.voteCounterBaselineState || null,
        demNomineeStrengthPts: Number(MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026?.demNomineeStrengthPts),
        repNomineeStrengthPts: Number(MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026?.repNomineeStrengthPts),
        blendWeight: Number(MODELED_CONTEST_DEFINITIONS?.us_senate_model_2026?.blendWeight)
      };
    });

    console.log(JSON.stringify(result, null, 2));
  } finally {
    try {
      if (browser) await browser.close();
    } catch (_) {}
    if (!serverClosed) {
      try {
        server.kill();
      } catch (_) {}
    }
  }
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exitCode = 1;
});
