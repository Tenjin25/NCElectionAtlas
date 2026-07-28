const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..');

const APP_READY_TIMEOUT = 180_000;

async function waitForAtlasReady(page) {
  await page.waitForSelector('#map .mapboxgl-canvas', { timeout: APP_READY_TIMEOUT });
  await page.waitForSelector('#contestSelect', { timeout: APP_READY_TIMEOUT });
}

async function waitForSplitTicketOptions(page) {
  await page.waitForFunction(() => {
    const sel = document.getElementById('contestSelect');
    if (!sel) return false;
    const values = Array.from(sel.options || [])
      .map((opt) => (opt && opt.value ? String(opt.value).trim() : ''))
      .filter(Boolean);
    const hasPresident = values.some((v) => v.startsWith('president_2024'));
    const hasGovernor = values.some((v) => v.startsWith('governor_2024'));
    return hasPresident && hasGovernor;
  }, { timeout: APP_READY_TIMEOUT });
}

async function pickContestKey(page) {
  await page.waitForFunction(() => {
    const sel = document.getElementById('contestSelect');
    return !!(sel && Array.from(sel.options || []).some((o) => (o?.value || '').trim()));
  }, { timeout: APP_READY_TIMEOUT });

  return page.evaluate(() => {
    const sel = document.getElementById('contestSelect');
    const values = Array.from(sel?.options || [])
      .map((opt) => (opt && opt.value ? String(opt.value).trim() : ''))
      .filter(Boolean);
    return (
      values.find((v) => v.startsWith('attorney_general_2024')) ||
      values.find((v) => v.startsWith('governor_2024')) ||
      values.find((v) => v.startsWith('us_senate_2022')) ||
      values.find((v) => v.startsWith('president_2024')) ||
      values[0] ||
      ''
    );
  });
}

async function flyToPrecinct(page, query = 'Wake 01-14') {
  await page.fill('#desktop-fly-search', query);
  await page.press('#desktop-fly-search', 'Enter');
}

test('official county totals override county aggregates without changing precinct rows', async ({ page }) => {
  await page.goto('/index.html', { waitUntil: 'domcontentloaded', timeout: APP_READY_TIMEOUT });
  await page.waitForFunction(() => (
    typeof attachOfficialCountyTotalsToRows === 'function' &&
    typeof buildCountyAggregateBundleFromSliceRows === 'function'
  ), { timeout: APP_READY_TIMEOUT });

  const snapshot = await page.evaluate(() => {
    const rows = [{
      year: 2024,
      county: 'WAKE - 01-01',
      president_dem: 40,
      president_rep: 30,
      president_other: 2,
      president_total: 72
    }];
    attachOfficialCountyTotalsToRows(rows, {
      county_totals: {
        WAKE: { dem_votes: 50, rep_votes: 35, other_votes: 3, total_votes: 88 }
      }
    });
    const bundle = buildCountyAggregateBundleFromSliceRows(rows, 'president');
    return {
      rowCount: rows.length,
      precinctDem: rows[0].president_dem,
      county: bundle?.totalsByCounty?.get('WAKE') || null,
      statewide: bundle?.statewide || null
    };
  });

  expect(snapshot.rowCount).toBe(1);
  expect(snapshot.precinctDem).toBe(40);
  expect(snapshot.county).toEqual({ dem: 50, rep: 35, other: 3, total: 88 });
  expect(snapshot.statewide).toEqual({ dem: 50, rep: 35, other: 3, total: 88 });
});

test('compact county slices stay small and contain one row per county', async ({ request }) => {
  const response = await request.get('/data/county_contests/governor_2000.json');
  expect(response.ok()).toBeTruthy();
  const body = await response.body();
  const payload = JSON.parse(body.toString('utf8'));
  expect(body.length).toBeLessThan(50_000);
  expect(payload.rows).toHaveLength(100);
  expect(payload.rows.every((row) => row && row.county && !String(row.county).includes(' - '))).toBeTruthy();
});

test('DRA colors are the default while Atlas remains a persisted option', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('nc-atlas-partisan-palette', 'dra');
    window.localStorage.setItem('nc-atlas-partisan-palette-v2', 'atlas');
    window.__firstMarginLegendColors = null;
    const observer = new MutationObserver(() => {
      const segments = document.querySelectorAll('.legend-spectrum.margins .legend-segment');
      if (segments.length !== 15 || window.__firstMarginLegendColors) return;
      window.__firstMarginLegendColors = Array.from(segments).map((el) => getComputedStyle(el).backgroundColor);
      observer.disconnect();
    });
    observer.observe(document, { childList: true, subtree: true });
  });
  await page.goto('/index.html', { waitUntil: 'domcontentloaded', timeout: APP_READY_TIMEOUT });
  await expect.poll(() => page.evaluate(() => window.__ATLAS_BUILD__ || '')).toBe('2026-07-28-historical-districts');
  const toggle = page.locator('#dra-palette-toggle');
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('body')).toHaveClass(/dra-palette/);
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem('nc-atlas-partisan-palette'))).toBeNull();
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem('nc-atlas-partisan-palette-v2'))).toBeNull();
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem('nc-atlas-partisan-palette-v3'))).toBeNull();
  const firstMarginLegendColors = await page.evaluate(() => window.__firstMarginLegendColors);
  expect(firstMarginLegendColors).toHaveLength(15);
  expect(firstMarginLegendColors.slice(0, 5)).toEqual([
    'rgb(104, 0, 12)',
    'rgb(148, 0, 22)',
    'rgb(185, 18, 39)',
    'rgb(213, 43, 63)',
    'rgb(241, 102, 114)'
  ]);
  expect(firstMarginLegendColors.slice(10, 15)).toEqual([
    'rgb(70, 153, 229)',
    'rgb(31, 117, 189)',
    'rgb(8, 99, 168)',
    'rgb(6, 74, 128)',
    'rgb(4, 52, 92)'
  ]);
  await page.locator('.contest-tools-more > summary').click();

  const safeSegment = page.locator('.legend-spectrum.margins .legend-segment:nth-child(4)');
  const draColor = await safeSegment.evaluate((el) => el.style.background);
  expect(draColor).toBe('rgb(213, 43, 63)');
  const draScale = await page.locator('.legend-spectrum.margins .legend-segment').evaluateAll(
    (segments) => segments.map((el) => el.style.background)
  );
  expect(draScale).toEqual([
    'rgb(104, 0, 12)',
    'rgb(148, 0, 22)',
    'rgb(185, 18, 39)',
    'rgb(213, 43, 63)',
    'rgb(241, 102, 114)',
    'rgb(245, 143, 150)',
    'rgb(248, 190, 194)',
    'rgb(247, 247, 247)',
    'rgb(182, 213, 245)',
    'rgb(120, 175, 233)',
    'rgb(70, 153, 229)',
    'rgb(31, 117, 189)',
    'rgb(8, 99, 168)',
    'rgb(6, 74, 128)',
    'rgb(4, 52, 92)'
  ]);
  await expect(page.locator('.legend-spectrum.margins .legend-segment').first()).toHaveCSS('opacity', '1');

  await page.evaluate(() => window.updateLegendColors('shift'));
  const draShiftScale = await page.locator('.legend-spectrum.shift .legend-segment').evaluateAll(
    (segments) => segments.map((el) => el.style.background)
  );
  expect(draShiftScale).toEqual([
    'rgb(8, 99, 168)',
    'rgb(31, 117, 189)',
    'rgb(70, 153, 229)',
    'rgb(247, 247, 247)',
    'rgb(241, 102, 114)',
    'rgb(213, 43, 63)',
    'rgb(185, 18, 39)'
  ]);

  await page.evaluate(() => window.updateLegendColors('winners'));
  const draWinnerScale = await page.locator('.legend-swatch-grid .legend-color').evaluateAll(
    (segments) => segments.map((el) => el.style.background)
  );
  expect(draWinnerScale).toEqual([
    'rgb(31, 117, 189)',
    'rgb(213, 43, 63)',
    'rgb(247, 247, 247)'
  ]);

  await page.evaluate(() => window.updateLegendColors('flips'));
  const draFlipScale = await page.locator('.legend-swatch-grid .legend-color').evaluateAll(
    (segments) => segments.map((el) => el.style.background)
  );
  expect(draFlipScale).toEqual([
    'rgb(31, 117, 189)',
    'rgb(213, 43, 63)',
    'rgb(247, 247, 247)'
  ]);
  await page.evaluate(() => window.updateLegendColors('margins'));

  await page.reload({ waitUntil: 'domcontentloaded', timeout: APP_READY_TIMEOUT });
  await expect(page.locator('#dra-palette-toggle')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('body')).toHaveClass(/dra-palette/);

  await page.locator('.contest-tools-more > summary').click();
  await page.locator('#dra-palette-toggle').click();
  await expect(page.locator('#dra-palette-toggle')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('body')).not.toHaveClass(/dra-palette/);
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem('nc-atlas-partisan-palette-v3'))).toBe('atlas');
  const restoredSafeColor = await page.locator('.legend-spectrum.margins .legend-segment:nth-child(4)').evaluate(
    (el) => el.style.background
  );
  expect(restoredSafeColor).toBe('rgb(239, 59, 44)');
  await expect(page.locator('.legend-spectrum.margins .legend-segment').first()).toHaveCSS('opacity', '1');

  await page.reload({ waitUntil: 'domcontentloaded', timeout: APP_READY_TIMEOUT });
  await expect(page.locator('#dra-palette-toggle')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('body')).not.toHaveClass(/dra-palette/);
  await page.locator('.contest-tools-more > summary').click();
  const persistedAtlasColor = await page.locator('.legend-spectrum.margins .legend-segment:nth-child(4)').evaluate(
    (el) => el.style.background
  );
  expect(persistedAtlasColor).toBe('rgb(239, 59, 44)');
});

test('2022-lines NC-13 2016 presidential result matches snapshot margin without changing total', async ({ request }) => {
  const response = await request.get('/data/district_contests/congressional_president_2016.json');
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const row = payload?.general?.results?.['13'];

  expect(row).toBeTruthy();
  expect(row).toMatchObject({
    dem_votes: 151987,
    rep_votes: 159607,
    other_votes: 14033,
    total_votes: 325627,
    margin: 7620,
    margin_pct: 2.34,
    winner: 'REP'
  });
  expect(row.dem_votes + row.rep_votes + row.other_votes).toBe(row.total_votes);
  expect(((row.rep_votes - row.dem_votes) / row.total_votes) * 100).toBeCloseTo(2.34, 2);
});

test('ordinary county modes do not block on previous precinct results', async ({ request }) => {
  const response = await request.get('/index.html');
  expect(response.ok()).toBeTruthy();
  const source = await response.text();

  expect(source).toContain('const rows = includePrecinctMargins');
  expect(source).toContain(': await loadCountyContestSlice(priorType, cy);');
  expect(source).toContain("if (mode === 'shift' || mode === 'flips') {");
  expect(source).toContain('populate flip details for hover in the background');
  expect(source).toContain('|m:${mode}|palette:${palette}|lines:');
  expect(source).toContain("activePartisanPaletteKey() === 'dra'");
  expect(source).toContain('countyBaseOpacity = districtBaseOpacity;');
  expect(source).toContain('houseBaseOpacity = districtBaseOpacity;');
  expect(source).toContain('senateBaseOpacity = districtBaseOpacity;');
  expect(source).toContain("id: 'county-stroke-casing'");
  expect(source).toContain("data-initial-partisan-palette', initialPalette");
  expect(source).toContain('background: var(--initial-margin-1)');
});

test('2020 president allocates OS early-vote centers into geographic precincts', async () => {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(repoRoot, 'data', 'contests', 'manifest.json'), 'utf8')
  );
  const contestFiles2020 = (manifest.files || [])
    .filter((entry) => Number(entry.year) === 2020 && !entry.scope)
    .map((entry) => String(entry.file || ''))
    .filter(Boolean);
  const residualEarlyVoteCenters = [];
  contestFiles2020.forEach((fileName) => {
    const contestPayload = JSON.parse(
      fs.readFileSync(path.join(repoRoot, 'data', 'contests', fileName), 'utf8')
    );
    (contestPayload.rows || []).forEach((row) => {
      if (/^[A-Z .'-]+ - OS/i.test(String(row.county || ''))) {
        residualEarlyVoteCenters.push(`${fileName}:${row.county}`);
      }
    });
  });

  const payload = JSON.parse(
    fs.readFileSync(path.join(repoRoot, 'data', 'contests', 'president_2020.json'), 'utf8')
  );
  const rows = (payload.rows || []).filter((row) => String(row.county || '').startsWith('CABARRUS - '));
  const totals = rows.reduce((sum, row) => ({
    dem: sum.dem + Number(row.dem_votes || 0),
    rep: sum.rep + Number(row.rep_votes || 0),
    other: sum.other + Number(row.other_votes || 0),
    total: sum.total + Number(row.total_votes || 0)
  }), { dem: 0, rep: 0, other: 0, total: 0 });

  expect(residualEarlyVoteCenters).toEqual([]);
  expect(totals).toEqual({
    dem: 52162,
    rep: 63237,
    other: 1828,
    total: 117227
  });
});

test('Davidson Arcadia 04 and Boone 06 aliases resolve to OneMap precinct codes', async ({ request }) => {
  const response = await request.get('/data/mappings/precinct_variant_overrides.json');
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const aliases = payload?.counties?.DAVIDSON;

  expect(aliases).toBeTruthy();
  expect(aliases['04 ARCADIA #04']).toEqual(['04']);
  expect(aliases['04_ARCADIA #04']).toEqual(['04']);
  expect(aliases['ARCADIA 04']).toEqual(['04']);
  expect(aliases['06 BOONE #06']).toEqual(['06']);
  expect(aliases['06_BOONE #06']).toEqual(['06']);
  expect(aliases['BOONE 06']).toEqual(['06']);
});

test('2018 Supreme Court county totals keep Anglin separate from Jackson', async ({ request }) => {
  const response = await request.get('/data/county_contests/nc_supreme_court_associate_justice_seat_01_2018.json');
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const totals = payload.rows.reduce((sum, row) => ({
    dem: sum.dem + Number(row.dem_votes || 0),
    rep: sum.rep + Number(row.rep_votes || 0),
    other: sum.other + Number(row.other_votes || 0),
    total: sum.total + Number(row.total_votes || 0)
  }), { dem: 0, rep: 0, other: 0, total: 0 });

  expect(payload.rows).toHaveLength(100);
  expect(totals).toEqual({ dem: 1812751, rep: 1246263, other: 598753, total: 3657767 });
  expect(payload.rows.every((row) => row.rep_candidate === 'Barbara Jackson')).toBeTruthy();
});

test('2002 US Senate county totals come from the November general election', async ({ request }) => {
  const response = await request.get('/data/county_contests/us_senate_2002.json');
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const totals = payload.rows.reduce((sum, row) => ({
    dem: sum.dem + Number(row.dem_votes || 0),
    rep: sum.rep + Number(row.rep_votes || 0),
    other: sum.other + Number(row.other_votes || 0),
    total: sum.total + Number(row.total_votes || 0)
  }), { dem: 0, rep: 0, other: 0, total: 0 });

  expect(payload.rows).toHaveLength(100);
  expect(totals).toEqual({ dem: 1047983, rep: 1248664, other: 34534, total: 2331181 });
});

test.describe('North Carolina Election Atlas regression checks', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/index.html');
    await waitForAtlasReady(page);
  });

  test('loads with no contest selected and reveal overlay default', async ({ page }) => {
    await expect(page.locator('#contestSelect')).toHaveValue('');
    await expect(page.locator('#overlay-opacity-preset')).toHaveValue('focus');
    await expect(page.locator('#context-contest')).toContainText('Select a contest');

    const countyFillOpacity = await page.evaluate(() => {
      try {
        if (typeof map === 'undefined' || !map || !map.getLayer || !map.getLayer('county-fill')) return null;
        return map.getPaintProperty('county-fill', 'fill-opacity');
      } catch (_) {
        return null;
      }
    });

    if (typeof countyFillOpacity === 'number') {
      expect(countyFillOpacity).toBeLessThanOrEqual(0.12);
    }
  });

  test('split-ticket toggle enables President vs Governor overlay', async ({ page }) => {
    await waitForSplitTicketOptions(page);

    const contestKeys = await page.evaluate(() => {
      const sel = document.getElementById('contestSelect');
      const values = Array.from(sel?.options || [])
        .map((opt) => (opt && opt.value ? String(opt.value).trim() : ''))
        .filter(Boolean);
      const presidentValue = values.find((v) => v.startsWith('president_2024')) || '';
      const governorValue = values.find((v) => v.startsWith('governor_2024')) || '';
      return { presidentValue, governorValue };
    });

    expect(contestKeys.presidentValue).toBeTruthy();
    expect(contestKeys.governorValue).toBeTruthy();

    await page.selectOption('#contestSelect', contestKeys.governorValue);
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      contestKeys.governorValue
    );

    await page.click('#split-ticket-toggle');
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      contestKeys.presidentValue
    );
    await expect(page.locator('#split-ticket-toggle')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('#context-contest')).toContainText(/President/i);

    const overlayState = await page.evaluate(() => {
      try {
        if (typeof map === 'undefined' || !map || !map.getLayer) return null;
        const countyLayer = map.getLayer('county-split-overlay-fill');
        if (!countyLayer) return null;
        const visibility = map.getLayoutProperty('county-split-overlay-fill', 'visibility');
        const opacity = map.getPaintProperty('county-split-overlay-fill', 'fill-opacity');
        return { visibility, opacity };
      } catch (_) {
        return null;
      }
    });
    expect(overlayState).toBeTruthy();
    expect(overlayState.visibility).toBe('visible');
    if (typeof overlayState.opacity === 'number') {
      expect(overlayState.opacity).toBeGreaterThan(0.05);
    }

    await page.click('#split-ticket-toggle');
    await expect(page.locator('#split-ticket-toggle')).toHaveAttribute('aria-pressed', 'false');
    await page.waitForFunction(
      () => {
        try {
          if (typeof map === 'undefined' || !map || !map.getLayer || !map.getLayer('county-split-overlay-fill')) return true;
          return map.getLayoutProperty('county-split-overlay-fill', 'visibility') === 'none';
        } catch (_) {
          return false;
        }
      }
    );
  });

  test('historical precinct backfill uses county fallback only for 2020 and older', async ({ page }) => {
    const snapshot = await page.evaluate(() => {
      if (typeof backfillHistoricalPrecinctResultsWithCountyFallback !== 'function') return null;

      precinctCentroidsData = {
        type: 'FeatureCollection',
        features: [
          { type: 'Feature', properties: { county_nam: 'Wake', prec_id: '01-01', precinct_norm: 'WAKE - 01-01' } },
          { type: 'Feature', properties: { county_nam: 'Wake', prec_id: '01-02', precinct_norm: 'WAKE - 01-02' } }
        ]
      };
      window.precinctsData = { type: 'FeatureCollection', features: [] };

      const older = new Map([
        ['WAKE - 01-01', {
          county: 'WAKE - 01-01',
          governor_dem: 60,
          governor_rep: 40,
          governor_other: 0,
          governor_total: 100,
          governor_margin_pct: -20,
          governor_winner: 'DEMOCRAT'
        }]
      ]);
      const countyAgg = {
        WAKE: {
          year: 2020,
          county: 'Wake',
          governor_dem: 600,
          governor_rep: 400,
          governor_other: 0,
          governor_total: 1000,
          governor_dem_candidate: 'Dem',
          governor_rep_candidate: 'Rep'
        }
      };

      const filledOlder = backfillHistoricalPrecinctResultsWithCountyFallback(older, countyAgg, 'governor', 2020);
      const olderFallback = older.get('WAKE - 01-02') || null;

      const newer = new Map();
      const filledNewer = backfillHistoricalPrecinctResultsWithCountyFallback(newer, countyAgg, 'governor', 2024);

      return {
        filledOlder,
        olderFallbackScope: String(olderFallback?.__fallback_scope || ''),
        olderFallbackReason: String(olderFallback?.__fallback_reason || ''),
        olderFallbackTotal: Number(olderFallback?.governor_total || 0),
        olderFallbackWinner: String(olderFallback?.governor_winner || ''),
        filledNewer,
        newerSize: newer.size
      };
    });

    expect(snapshot).toBeTruthy();
    expect(snapshot.filledOlder).toBeGreaterThanOrEqual(1);
    expect(snapshot.olderFallbackScope).toBe('county');
    expect(snapshot.olderFallbackReason).toBe('historical_unmatched_precinct');
    expect(snapshot.olderFallbackTotal).toBe(1000);
    expect(snapshot.olderFallbackWinner).toMatch(/DEMOCRAT/i);
    expect(snapshot.filledNewer).toBe(0);
    expect(snapshot.newerSize).toBe(0);
  });

  test('precinct search selection sets yellow-highlight target and zooms in', async ({ page }) => {
    await flyToPrecinct(page, 'Wake 01-14');

    await page.waitForFunction(() => {
      try {
        if (typeof selectedPrecinctNorm === 'undefined' || typeof map === 'undefined' || !map) return false;
        const toggleText = (document.getElementById('precinct-toggle')?.textContent || '').trim();
        return /^WAKE - /i.test(String(selectedPrecinctNorm || ''))
          && Number(map.getZoom()) >= 9.8
          && (toggleText === 'Precincts On' || toggleText === 'Precincts Loading');
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });

    const selectedState = await page.evaluate(() => {
      const selected = typeof selectedPrecinctNorm === 'undefined' ? '' : String(selectedPrecinctNorm || '');
      const zoom = (typeof map !== 'undefined' && map && typeof map.getZoom === 'function') ? Number(map.getZoom()) : 0;
      const toggleText = String(document.getElementById('precinct-toggle')?.textContent || '').trim();
      const searchValue = String(document.getElementById('county-search')?.value || '').trim();
      return { selected, zoom, searchValue, toggleText };
    });

    expect(selectedState.selected).toMatch(/^WAKE - /i);
    expect(selectedState.zoom).toBeGreaterThanOrEqual(9.8);
    expect(['Precincts On', 'Precincts Loading']).toContain(selectedState.toggleText);
    expect(selectedState.searchValue.toUpperCase()).toContain('WAKE -');
  });

  test('selecting a precinct pins precinct trend context', async ({ page }) => {
    const contestKey = await pickContestKey(page);
    expect(contestKey).toBeTruthy();

    await page.selectOption('#contestSelect', contestKey);
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      contestKey
    );

    await flyToPrecinct(page, 'Wake 01-14');
    await page.waitForFunction(() => {
      try {
        if (typeof selectedPrecinctNorm === 'undefined' || typeof map === 'undefined' || !map) return false;
        return /^WAKE - /i.test(String(selectedPrecinctNorm || '')) && Number(map.getZoom()) >= 9.8;
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });

    await page.waitForFunction(() => {
      try {
        const pinnedMeta = (typeof voteCounterPinned !== 'undefined' && voteCounterPinned) ? voteCounterPinned.meta : null;
        const title = (document.getElementById('vote-context-title')?.textContent || '').trim();
        const caption = (document.getElementById('focus-trend-caption')?.textContent || '').trim();
        const chartText = (document.getElementById('focus-trend-chart')?.textContent || '').trim();
        const trendUpdated = /Loading trend history|Trend at a glance|No historical trend data available|Failed to load trend history/i.test(chartText);
        return !!(pinnedMeta && pinnedMeta.kind === 'precinct' && /^Selected:/i.test(title) && /WAKE -/i.test(caption) && trendUpdated);
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });

    const pinnedSnapshot = await page.evaluate(() => {
      const pinnedMeta = (typeof voteCounterPinned !== 'undefined' && voteCounterPinned) ? voteCounterPinned.meta : null;
      return {
        kind: pinnedMeta?.kind || '',
        precinctNorm: String(pinnedMeta?.precinctNorm || ''),
        caption: String(document.getElementById('focus-trend-caption')?.textContent || ''),
        title: String(document.getElementById('vote-context-title')?.textContent || '')
      };
    });

    expect(pinnedSnapshot.kind).toBe('precinct');
    expect(pinnedSnapshot.precinctNorm).toMatch(/^WAKE - /i);
    expect(pinnedSnapshot.caption).toMatch(/WAKE -/i);
    expect(pinnedSnapshot.title).toMatch(/^Selected:/i);

    await page.waitForFunction(() => {
      try {
        const chartText = String(document.getElementById('focus-trend-chart')?.textContent || '').trim();
        return /Trend at a glance|No historical trend data available|Failed to load trend history/i.test(chartText);
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });
  });

  test('exact Wake precinct result outranks a colliding generated alias', async ({ page }) => {
    await page.selectOption('#contestSelect', 'president_2020');
    await page.waitForFunction(
      () => (
        document.getElementById('contestSelect')?.value === 'president_2020' &&
        typeof lastCompletedContestSelection !== 'undefined' &&
        lastCompletedContestSelection === 'president_2020'
      ),
      { timeout: APP_READY_TIMEOUT }
    );

    await flyToPrecinct(page, 'Wake 01-25');
    await page.waitForFunction(() => {
      try {
        const pinned = typeof voteCounterPinned !== 'undefined' ? voteCounterPinned : null;
        return pinned?.meta?.kind === 'precinct' &&
          String(pinned?.meta?.precinctNorm || '').toUpperCase() === 'WAKE - 01-25';
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });

    const pinnedVotes = await page.evaluate(() => ({
      dem: Number(voteCounterPinned?.demVotes || 0),
      rep: Number(voteCounterPinned?.repVotes || 0),
      other: Number(voteCounterPinned?.otherVotes || 0),
      precinctNorm: String(voteCounterPinned?.meta?.precinctNorm || '')
    }));

    expect(pinnedVotes).toEqual({
      dem: 792,
      rep: 51,
      other: 10,
      precinctNorm: 'WAKE - 01-25'
    });
  });

  test('pinned precinct side trend stays in sync after contest switch', async ({ page }) => {
    const firstContestKey = await pickContestKey(page);
    expect(firstContestKey).toBeTruthy();

    await page.selectOption('#contestSelect', firstContestKey);
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      firstContestKey
    );

    await flyToPrecinct(page, 'Wake 01-14');
    await page.waitForFunction(() => {
      try {
        if (typeof selectedPrecinctNorm === 'undefined' || typeof map === 'undefined' || !map) return false;
        return /^WAKE - /i.test(String(selectedPrecinctNorm || '')) && Number(map.getZoom()) >= 9.8;
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });

    await page.waitForFunction(() => {
      try {
        const pinnedMeta = (typeof voteCounterPinned !== 'undefined' && voteCounterPinned) ? voteCounterPinned.meta : null;
        const title = (document.getElementById('vote-context-title')?.textContent || '').trim();
        const caption = (document.getElementById('focus-trend-caption')?.textContent || '').trim();
        return !!(pinnedMeta && pinnedMeta.kind === 'precinct' && /^Selected:/i.test(title) && /WAKE -/i.test(caption));
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });

    const secondContestKey = await page.evaluate((current) => {
      const sel = document.getElementById('contestSelect');
      const values = Array.from(sel?.options || [])
        .map((opt) => (opt && opt.value ? String(opt.value).trim() : ''))
        .filter(Boolean);
      const preferred = [
        'governor_2024',
        'president_2024',
        'us_senate_2022',
        'attorney_general_2024'
      ];
      for (const target of preferred) {
        const hit = values.find((v) => v === target && v !== current);
        if (hit) return hit;
      }
      return values.find((v) => v !== current) || '';
    }, firstContestKey);
    expect(secondContestKey).toBeTruthy();

    await page.selectOption('#contestSelect', secondContestKey);
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      secondContestKey
    );

    const splitAt = secondContestKey.lastIndexOf('_');
    const expectedType = secondContestKey.slice(0, splitAt);
    const expectedYear = Number(secondContestKey.slice(splitAt + 1));

    await page.waitForFunction(({ expectedType, expectedYear }) => {
      try {
        const pinned = (typeof voteCounterPinned !== 'undefined' && voteCounterPinned) ? voteCounterPinned : null;
        const meta = pinned?.meta || null;
        if (!meta || meta.kind !== 'precinct') return false;
        if (String(meta.contestType || '') !== String(expectedType || '')) return false;
        if (Number(meta.year) !== Number(expectedYear)) return false;
        const subtitle = String(document.getElementById('vote-context-sub')?.textContent || '').trim();
        const chartText = String(document.getElementById('focus-trend-chart')?.textContent || '').trim();
        return subtitle.includes(String(expectedYear)) && /Trend at a glance|No historical trend data available|Failed to load trend history/i.test(chartText);
      } catch (_) {
        return false;
      }
    }, { expectedType, expectedYear }, { timeout: APP_READY_TIMEOUT });
  });

  test('county trajectory card uses scoped tone classes, edge-case labels, and census context', async ({ page }) => {
    const contestKey = await pickContestKey(page);
    expect(contestKey).toBeTruthy();

    await page.selectOption('#contestSelect', contestKey);
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      contestKey
    );

    await page.evaluate(() => {
      showCountyDetails('Wake');
    });

    await page.waitForSelector('.focus-trajectory', { timeout: APP_READY_TIMEOUT });

    const statusText = (await page.locator('.focus-trajectory-status').textContent() || '').trim();
    expect(statusText).toMatch(/(?:Durable|Reinforcing|Emerging|Realigned)\s+(?:Democratic|Republican)\s+(?:Stronghold|Lean|Edge|Tilt)|Battleground/i);
    expect(statusText).not.toMatch(/Softening|On the Cusp|Toss-Up \(Balanced\)/i);
    await expect(page.locator('.focus-trajectory-strength')).toHaveCount(0);

    const labels = await page.locator('.focus-trajectory-label').allTextContents();
    expect(labels).toContain('Latest Result');
    expect(labels).toContain('Recent Shift');
    expect(labels).toContain('Long-Term Trend');

    await expect(page.locator('.focus-census-insight')).toContainText('County Census Insight');
    await expect(page.locator('.focus-census-insight')).toContainText(/Population up|Population down|Population roughly flat|Urban anchor/i);
    await expect(page.locator('.focus-census-insight')).toContainText(/2025 estimate|2024 to 2025|statewide/i);

    const censusSnapshot = await page.evaluate(() => {
      const context = typeof getNcCensusContext === 'function' ? getNcCensusContext('WAKE') : null;
      const html = context && typeof renderCensusContextHTML === 'function'
        ? renderCensusContextHTML(context)
        : '';
      return {
        title: String(context?.title || ''),
        signal: String(context?.signalLabel || ''),
        pattern: String(context?.patternLabel || ''),
        source: String(context?.sourceNote || ''),
        html
      };
    });
    expect(censusSnapshot.title).toBe('Census Context');
    expect(censusSnapshot.signal).toMatch(/since 2020/i);
    expect(censusSnapshot.pattern).toBeTruthy();
    expect(censusSnapshot.source).toMatch(/Vintage 2025/i);
    expect(censusSnapshot.html).toContain('Population signal');
    expect(censusSnapshot.html).toContain('Growth pattern');
    expect(censusSnapshot.html).toContain('Why it matters');

    const emergingEdgeSnapshot = await page.evaluate(() => {
      if (typeof classifyCountyTrajectory !== 'function') return null;
      return classifyCountyTrajectory([
        { year: 2008, winner: 'DEM', margin_pct: 7.2 },
        { year: 2020, winner: 'REP', margin_pct: 1.6 },
        { year: 2024, winner: 'REP', margin_pct: 4.4 }
      ]);
    });
    expect(emergingEdgeSnapshot?.status).toMatch(/Emerging Republican Edge/i);

    const emergingTiltSnapshot = await page.evaluate(() => {
      if (typeof classifyCountyTrajectory !== 'function') return null;
      return classifyCountyTrajectory([
        { year: 2008, winner: 'DEM', margin_pct: 6.4 },
        { year: 2020, winner: 'REP', margin_pct: 0.9 },
        { year: 2024, winner: 'REP', margin_pct: 3.1 }
      ]);
    });
    expect(emergingTiltSnapshot?.status).toMatch(/Emerging Republican Tilt/i);

    const rawToneClasses = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.focus-trajectory *'))
        .flatMap((el) => Array.from(el.classList || []))
        .filter((cls) => ['dem', 'rep', 'competitive', 'neutral', 'latest', 'shift'].includes(cls));
    });

    expect(rawToneClasses).toEqual([]);
  });

  test('2026 modeled Senate and Supreme Court contests synthesize county and district slices', async ({ page }) => {
    await page.waitForFunction(() => {
      const sel = document.getElementById('contestSelect');
      const values = Array.from(sel?.options || [])
        .map((opt) => (opt && opt.value ? String(opt.value).trim() : ''))
        .filter(Boolean);
      return values.includes('us_senate_model_2026') && values.includes('nc_supreme_court_model_2026');
    }, { timeout: APP_READY_TIMEOUT });

    const modeledSnapshot = await page.evaluate(async () => {
      const sel = document.getElementById('contestSelect');
      const options = Array.from(sel?.options || []).reduce((acc, opt) => {
        const value = opt && opt.value ? String(opt.value).trim() : '';
        if (value) acc[value] = String(opt.textContent || '').trim();
        return acc;
      }, {});

      const senateRows = await loadContestSlice('us_senate_model', 2026);
      const courtRows = await loadContestSlice('nc_supreme_court_model', 2026);
      const senateDistrictNode = await loadDistrictSlice('congressional', 'us_senate_model', 2026);
      const senateStateHouseNode = await loadDistrictSlice('state_house', 'us_senate_model', 2026);
      const courtDistrictNode = await loadDistrictSlice('congressional', 'nc_supreme_court_model', 2026);
      const senateDefinition = getModeledContestDefinition('us_senate_model', 2026);
      const candidateStrengthTotal = (name) => Object.values(senateDefinition?.candidateStatewideStrengthComponentsPts?.[name] || {})
        .reduce((sum, value) => sum + Number(value || 0), 0);
      const ruralCooperBoost = Number(senateDefinition?.candidateCountyTypeBoostsPts?.['Roy Cooper']?.rural);
      const senateCountyOfficial = senateRows.reduce((counties, row) => {
        const county = String(row?.county || '').toUpperCase().split(' - ')[0].trim();
        if (!county) return counties;
        const totals = counties[county] || { dem: 0, rep: 0, total: 0 };
        totals.dem += Number(row?.us_senate_model_dem || 0);
        totals.rep += Number(row?.us_senate_model_rep || 0);
        totals.total += Number(row?.us_senate_model_total || 0);
        counties[county] = totals;
        return counties;
      }, {});
      const senateOfficial = senateCountyOfficial;
      const countyModeledRow = (county) => senateRows.find(
        row => String(row?.county || '').toUpperCase().split(' - ')[0].trim() === county
      ) || null;
      const nashModeledRow = countyModeledRow('NASH');
      const wilsonModeledRow = countyModeledRow('WILSON');
      const wataugaModeledRow = countyModeledRow('WATAUGA');
      const gastonModeledRow = countyModeledRow('GASTON');
      const buncombeCountyOfficial = senateCountyOfficial.BUNCOMBE || null;
      const ansonCountyOfficial = senateCountyOfficial.ANSON || null;
      const alamanceCountyOfficial = senateCountyOfficial.ALAMANCE || null;
      const cabarrusCountyOfficial = senateCountyOfficial.CABARRUS || null;
      const cumberlandCountyOfficial = senateCountyOfficial.CUMBERLAND || null;
      const granvilleCountyOfficial = senateCountyOfficial.GRANVILLE || null;
      const guilfordCountyOfficial = senateCountyOfficial.GUILFORD || null;
      const northamptonCountyOfficial = senateCountyOfficial.NORTHAMPTON || null;
      const pittCountyOfficial = senateCountyOfficial.PITT || null;
      const wataugaCountyOfficial = senateCountyOfficial.WATAUGA || null;
      const hokeCountyOfficial = senateCountyOfficial.HOKE || null;
      const harnettCountyOfficial = senateCountyOfficial.HARNETT || null;
      const hokeOfficial = senateOfficial.HOKE || null;
      const hokeUnderlying = senateRows
        .filter(row => String(row?.county || '').toUpperCase().startsWith('HOKE'))
        .reduce((acc, row) => {
          acc.dem += Number(row?.us_senate_model_dem || 0);
          acc.rep += Number(row?.us_senate_model_rep || 0);
          acc.total += Number(row?.us_senate_model_total || 0);
          return acc;
        }, { dem: 0, rep: 0, total: 0 });
      const margin = (totals) => Number(totals?.total || totals?.total_votes || 0) > 0
        ? ((Number(totals?.rep || totals?.rep_votes || 0) - Number(totals?.dem || totals?.dem_votes || 0)) / Number(totals?.total || totals?.total_votes || 0)) * 100
        : 0;
      const aggregate = (rows) => Object.values(rows || {}).reduce((sum, row) => {
        sum.dem += Number(row?.dem || row?.dem_votes || 0);
        sum.rep += Number(row?.rep || row?.rep_votes || 0);
        sum.total += Number(row?.total || row?.total_votes || 0);
        return sum;
      }, { dem: 0, rep: 0, total: 0 });
      // Match the live statewide panel: (R−D)/total including other (post-clamp backend).
      const uiSignedMargin = (totals) => Number(totals?.total || 0) > 0
        ? ((Number(totals.rep) - Number(totals.dem)) / Number(totals.total)) * 100
        : 0;
      const withImpliedTotal = (totals) => {
        const dem = Number(totals?.dem || 0);
        const rep = Number(totals?.rep || 0);
        const total = Number(totals?.total || 0);
        return { dem, rep, total: total > 0 ? total : (dem + rep) };
      };
      const senateStatewideUiMargin = uiSignedMargin(withImpliedTotal(aggregate(senateCountyOfficial)));
      const senatePrecinctUiMargin = uiSignedMargin(withImpliedTotal(senateRows.reduce((sum, row) => {
        sum.dem += Number(row?.us_senate_model_dem || 0);
        sum.rep += Number(row?.us_senate_model_rep || 0);
        sum.total += Number(row?.us_senate_model_total || 0);
        return sum;
      }, { dem: 0, rep: 0, total: 0 })));
      const senateDistrictUiMargin = uiSignedMargin(withImpliedTotal(aggregate(senateDistrictNode?.general?.results)));
      const senateStateHouseUiMargin = uiSignedMargin(withImpliedTotal(aggregate(senateStateHouseNode?.general?.results)));
      const senateStateHouseResults = senateStateHouseNode?.general?.results || {};
      const senateStateHouseSeats = Object.values(senateStateHouseResults).reduce((seats, row) => {
        const signed = margin(row);
        if (signed > 0) seats.rep += 1;
        else if (signed < 0) seats.dem += 1;
        else seats.tie += 1;
        return seats;
      }, { dem: 0, rep: 0, tie: 0 });
      const senateStateHouseSignedMarginsMatchWinners = Object.values(senateStateHouseResults).every(row => {
        const signed = Number(row?.margin_pct);
        const winner = String(row?.winner || '').toUpperCase();
        return (winner === 'DEM' && signed < 0)
          || (winner === 'REP' && signed > 0)
          || (winner === 'TIE' && signed === 0);
      });

      return {
        senateOptionText: options.us_senate_model_2026 || '',
        courtOptionText: options.nc_supreme_court_model_2026 || '',
        senateRows: senateRows.length,
        senateCountyRows: Object.keys(senateCountyOfficial).length,
        courtRows: courtRows.length,
        senateOfficialCount: Object.keys(senateOfficial).length,
        nashCountyOfficialMargin: margin(senateCountyOfficial.NASH),
        nashLocalCandidateEffect: Number(nashModeledRow?.__model_candidate_effect_local_d_pts),
        wilsonCountyOfficialMargin: margin(senateCountyOfficial.WILSON),
        wilsonLocalCandidateEffect: Number(wilsonModeledRow?.__model_candidate_effect_local_d_pts),
        wataugaLocalCandidateEffect: Number(wataugaModeledRow?.__model_candidate_effect_local_d_pts),
        gastonLocalCandidateEffect: Number(gastonModeledRow?.__model_candidate_effect_local_d_pts),
        buncombeCountyOfficialMargin: margin(buncombeCountyOfficial),
        ansonCountyOfficialMargin: margin(ansonCountyOfficial),
        alamanceCountyOfficialMargin: margin(alamanceCountyOfficial),
        cabarrusCountyOfficialMargin: margin(cabarrusCountyOfficial),
        cumberlandCountyOfficialMargin: margin(cumberlandCountyOfficial),
        granvilleCountyOfficialMargin: margin(granvilleCountyOfficial),
        guilfordCountyOfficialMargin: margin(guilfordCountyOfficial),
        northamptonCountyOfficialMargin: margin(northamptonCountyOfficial),
        pittCountyOfficialMargin: margin(pittCountyOfficial),
        wataugaCountyOfficialMargin: margin(wataugaCountyOfficial),
        cooperStatewideStrength: candidateStrengthTotal('Roy Cooper'),
        whatleyStatewideStrength: candidateStrengthTotal('Michael Whatley'),
        districtCandidateStrengthNetDem: candidateStrengthTotal('Roy Cooper') - candidateStrengthTotal('Michael Whatley'),
        ruralCooperBoost,
        countiesWithRuralCooperBoost: senateRows.filter(row => Number(row?.__model_candidate_effect_county_type_d_pts) > 0).length,
        realignedSpecialCounties: Array.from(senateDefinition?.candidateBonusRealignedFormerDemFederalCounties || []),
        anomalySpecialCounties: Array.from(senateDefinition?.anomalyClampCounties || []),
        urbanConsensusGuardrailEnabled: !!senateDefinition?.senateUrbanAnchorConsensusGuardrailEnabled,
        urbanConsensusGuardrailMaxMargin: Number(senateDefinition?.senateUrbanAnchorConsensusMaxMarginPts),
        urbanMinDemOverPres: Number(senateDefinition?.senateUrbanMinDemOverPresPts),
        urbanMinDemOverSenate2022: Number(senateDefinition?.senateUrbanMinDemOverSenate2022Pts),
        chathamMinDemOverPres: Number(senateDefinition?.senateMetroAdjacentMinDemOverPresByCountyPts?.CHATHAM),
        granvilleMinDemOverPres: Number(senateDefinition?.senateMetroAdjacentMinDemOverPresByCountyPts?.GRANVILLE),
        wataugaFinalTarget: Number(senateDefinition?.senateFinalTargetMarginByCountyPts?.WATAUGA),
        reconcilePrecinctCountyTargets: !!senateDefinition?.senateReconcilePrecinctsToCountyTargets,
        urbanReferenceWake: Number(senateDefinition?.senateUrbanReferenceMaxMarginByCountyPts?.WAKE),
        urbanReferenceMecklenburg: Number(senateDefinition?.senateUrbanReferenceMaxMarginByCountyPts?.MECKLENBURG),
        urbanReferenceGuilford: Number(senateDefinition?.senateUrbanReferenceMaxMarginByCountyPts?.GUILFORD),
        urbanReferenceCumberland: Number(senateDefinition?.senateUrbanReferenceMaxMarginByCountyPts?.CUMBERLAND),
        turnoutWeightUrban: Number(senateDefinition?.senateStatewideTurnoutWeightByCountyType?.urban),
        turnoutWeightSuburban: Number(senateDefinition?.senateStatewideTurnoutWeightByCountyType?.suburban),
        turnoutWeightRural: Number(senateDefinition?.senateStatewideTurnoutWeightByCountyType?.rural),
        ruralMaxOverPres: Number(senateDefinition?.senateRuralMaxOverPresPts),
        robesonOverPresCap: Number(senateDefinition?.senateMaxOverPresRobesonCapPts),
        bladenOverPresCap: Number(senateDefinition?.senateMaxOverPresBladenCapPts),
        scotlandOverPresCap: Number(senateDefinition?.senateMaxOverPresScotlandCapPts),
        hokeCountyOfficialMargin: margin(hokeCountyOfficial),
        harnettCountyOfficialMargin: margin(harnettCountyOfficial),
        hokeOfficialMargin: margin(hokeOfficial),
        hokeUnderlyingMargin: margin(hokeUnderlying),
        senateDemCandidate: String(senateRows[0]?.us_senate_model_dem_candidate || ''),
        senateRepCandidate: String(senateRows[0]?.us_senate_model_rep_candidate || ''),
        courtDemCandidate: String(courtRows[0]?.nc_supreme_court_model_dem_candidate || ''),
        courtRepCandidate: String(courtRows[0]?.nc_supreme_court_model_rep_candidate || ''),
        senateDistricts: Object.keys(senateDistrictNode?.general?.results || {}).length,
        senateDistrictCandidateStrengthNetDem: Number(senateDistrictNode?.meta?.model_candidate_strength_net_dem_pts),
        senateDistrictStatewideAlignment: Number(senateDistrictNode?.meta?.model_statewide_alignment_pts),
        senateStateHouseSource: String(senateStateHouseNode?.meta?.source || ''),
        senateStateHouseCoverage: Number(senateStateHouseNode?.meta?.match_coverage_pct),
        senateStateHouseDistricts: Object.keys(senateStateHouseResults).length,
        senateStateHouseSeats,
        senateStateHouseSignedMarginsMatchWinners,
        senateStatewideUiMargin,
        senatePrecinctUiMargin,
        senateDistrictUiMargin,
        senateStateHouseUiMargin,
        courtDistricts: Object.keys(courtDistrictNode?.general?.results || {}).length
      };
    });

    expect(modeledSnapshot.senateOptionText).toBe('US Senate (2026) model');
    expect(modeledSnapshot.courtOptionText).toBe('NC Supreme Court Associate Justice Seat 1 (2026) Model');
    expect(modeledSnapshot.senateRows).toBeGreaterThan(2000);
    expect(modeledSnapshot.senateCountyRows).toBe(100);
    expect(modeledSnapshot.courtRows).toBeGreaterThan(2000);
    expect(modeledSnapshot.senateOfficialCount).toBe(100);
    expect(modeledSnapshot.nashCountyOfficialMargin).toBeLessThan(0);
    expect(modeledSnapshot.nashCountyOfficialMargin).toBeGreaterThan(-6);
    expect(modeledSnapshot.nashLocalCandidateEffect).toBeCloseTo(6.95, 2);
    expect(modeledSnapshot.wilsonCountyOfficialMargin).toBeLessThan(0);
    expect(modeledSnapshot.wilsonCountyOfficialMargin).toBeGreaterThan(-6);
    expect(modeledSnapshot.wilsonLocalCandidateEffect).toBeCloseTo(5.50, 2);
    expect(modeledSnapshot.wataugaLocalCandidateEffect).toBeCloseTo(0.60, 2);
    expect(modeledSnapshot.gastonLocalCandidateEffect).toBeCloseTo(1.60, 2);
    expect(modeledSnapshot.buncombeCountyOfficialMargin).toBeLessThan(-15);
    expect(modeledSnapshot.ansonCountyOfficialMargin).toBeGreaterThan(3);
    expect(modeledSnapshot.ansonCountyOfficialMargin).toBeLessThan(5);
    expect(modeledSnapshot.alamanceCountyOfficialMargin).toBeGreaterThan(5);
    expect(modeledSnapshot.alamanceCountyOfficialMargin).toBeLessThan(7);
    expect(modeledSnapshot.cabarrusCountyOfficialMargin).toBeGreaterThan(5);
    expect(modeledSnapshot.cabarrusCountyOfficialMargin).toBeLessThan(6);
    expect(modeledSnapshot.cumberlandCountyOfficialMargin).toBeLessThan(-5);
    expect(modeledSnapshot.granvilleCountyOfficialMargin).toBeGreaterThan(8);
    expect(modeledSnapshot.granvilleCountyOfficialMargin).toBeLessThan(10);
    expect(modeledSnapshot.guilfordCountyOfficialMargin).toBeLessThan(-23);
    expect(modeledSnapshot.guilfordCountyOfficialMargin).toBeGreaterThan(-26);
    expect(modeledSnapshot.northamptonCountyOfficialMargin).toBeLessThan(-14);
    expect(modeledSnapshot.pittCountyOfficialMargin).toBeLessThan(-6);
    expect(modeledSnapshot.wataugaCountyOfficialMargin).toBeGreaterThan(-8);
    expect(modeledSnapshot.wataugaCountyOfficialMargin).toBeLessThan(-6);
    expect(modeledSnapshot.cooperStatewideStrength).toBeCloseTo(1.90, 2);
    expect(modeledSnapshot.whatleyStatewideStrength).toBeCloseTo(0.55, 2);
    expect(modeledSnapshot.districtCandidateStrengthNetDem).toBeCloseTo(1.35, 2);
    expect(modeledSnapshot.ruralCooperBoost).toBeCloseTo(0.45, 2);
    expect(modeledSnapshot.countiesWithRuralCooperBoost).toBeGreaterThan(0);
    expect(modeledSnapshot.realignedSpecialCounties).toEqual(['ROBESON', 'BLADEN', 'SCOTLAND']);
    expect(modeledSnapshot.anomalySpecialCounties).toEqual(['ROBESON', 'BLADEN', 'SCOTLAND']);
    expect(modeledSnapshot.urbanConsensusGuardrailEnabled).toBe(true);
    expect(modeledSnapshot.urbanConsensusGuardrailMaxMargin).toBeCloseTo(-0.50, 2);
    expect(modeledSnapshot.urbanMinDemOverPres).toBeCloseTo(0.25, 2);
    expect(modeledSnapshot.urbanMinDemOverSenate2022).toBeCloseTo(0.35, 2);
    expect(modeledSnapshot.chathamMinDemOverPres).toBeCloseTo(2.00, 2);
    expect(modeledSnapshot.granvilleMinDemOverPres).toBeCloseTo(0.75, 2);
    expect(modeledSnapshot.wataugaFinalTarget).toBeCloseTo(-6.75, 2);
    expect(modeledSnapshot.reconcilePrecinctCountyTargets).toBe(true);
    expect(modeledSnapshot.urbanReferenceWake).toBeCloseTo(-26.43, 2);
    expect(modeledSnapshot.urbanReferenceMecklenburg).toBeCloseTo(-35.31, 2);
    expect(modeledSnapshot.urbanReferenceGuilford).toBeCloseTo(-24.00, 2);
    expect(modeledSnapshot.urbanReferenceCumberland).toBeCloseTo(-14.66, 2);
    expect(modeledSnapshot.turnoutWeightUrban).toBeCloseTo(0.775, 3);
    expect(modeledSnapshot.turnoutWeightSuburban).toBeCloseTo(0.934, 3);
    expect(modeledSnapshot.turnoutWeightRural).toBeCloseTo(1.345, 3);
    expect(modeledSnapshot.ruralMaxOverPres).toBeCloseTo(4.00, 2);
    expect(modeledSnapshot.robesonOverPresCap).toBeCloseTo(-0.75, 2);
    expect(modeledSnapshot.bladenOverPresCap).toBeCloseTo(-0.50, 2);
    expect(modeledSnapshot.scotlandOverPresCap).toBeCloseTo(-0.25, 2);
    // Hoke stays Dem on the official county path; underlying can move with statewide recenter.
    expect(modeledSnapshot.hokeCountyOfficialMargin).toBeLessThan(0);
    expect(modeledSnapshot.hokeCountyOfficialMargin).toBeLessThan(-8);
    expect(modeledSnapshot.hokeCountyOfficialMargin).toBeGreaterThan(-10);
    expect(modeledSnapshot.harnettCountyOfficialMargin).toBeGreaterThan(23);
    expect(modeledSnapshot.harnettCountyOfficialMargin).toBeLessThan(25);
    expect(modeledSnapshot.hokeOfficialMargin).toBeLessThan(0);
    expect(Math.abs(modeledSnapshot.hokeCountyOfficialMargin - modeledSnapshot.hokeOfficialMargin)).toBeLessThan(0.25);
    expect(modeledSnapshot.senateDemCandidate).toBe('Roy Cooper');
    expect(modeledSnapshot.senateRepCandidate).toBe('Michael Whatley');
    expect(modeledSnapshot.courtDemCandidate).toBe('Anita Earls');
    expect(modeledSnapshot.courtRepCandidate).toBe('Sarah Stevens');
    expect(modeledSnapshot.senateDistricts).toBeGreaterThan(0);
    expect(modeledSnapshot.senateDistrictCandidateStrengthNetDem).toBeCloseTo(1.35, 2);
    expect(modeledSnapshot.senateDistrictStatewideAlignment).toBeCloseTo(1.09, 2);
    expect(modeledSnapshot.senateStateHouseSource).toBe('modeled_precinct_crosswalk');
    expect(modeledSnapshot.senateStateHouseCoverage).toBeGreaterThan(99.99);
    expect(modeledSnapshot.senateStateHouseDistricts).toBe(120);
    expect(modeledSnapshot.senateStateHouseSeats).toEqual({ dem: 58, rep: 62, tie: 0 });
    expect(modeledSnapshot.senateStateHouseSignedMarginsMatchWinners).toBe(true);
    // Turnout composition restores an R+1.5–1.9 topline without changing county margins.
    expect(modeledSnapshot.senateStatewideUiMargin).toBeGreaterThan(1.50);
    expect(modeledSnapshot.senateStatewideUiMargin).toBeLessThan(1.90);
    expect(modeledSnapshot.senatePrecinctUiMargin).toBeGreaterThan(1.50);
    expect(modeledSnapshot.senatePrecinctUiMargin).toBeLessThan(1.90);
    expect(Math.abs(modeledSnapshot.senateDistrictUiMargin - modeledSnapshot.senatePrecinctUiMargin)).toBeLessThan(0.10);
    expect(Math.abs(modeledSnapshot.senateStateHouseUiMargin - modeledSnapshot.senatePrecinctUiMargin)).toBeLessThan(0.02);
    expect(modeledSnapshot.courtDistricts).toBeGreaterThan(0);

    await page.selectOption('#contestSelect', 'us_senate_model_2026');
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      'us_senate_model_2026'
    );
    await expect(page.locator('#context-contest')).toContainText('US Senate (2026) model');
  });

  test('story snapshot exports include selected layout variant in filename', async ({ page }) => {
    await page.evaluate(() => {
      const png1x1 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR4nGNgYGAAAAAEAAGjChXjAAAAAElFTkSuQmCC';
      HTMLCanvasElement.prototype.toDataURL = function toDataURLMock() {
        return `data:image/png;base64,${png1x1}`;
      };
    });

    for (const variant of ['balanced', 'instagram', 'tiktok']) {
      await page.selectOption('#snapshot-variant', variant);
      const downloadPromise = page.waitForEvent('download');
      await page.click('#snapshot-share-btn');
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toContain(`-${variant}-`);
    }
  });
});
