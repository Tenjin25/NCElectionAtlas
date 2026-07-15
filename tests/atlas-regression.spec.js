const { test, expect } = require('@playwright/test');

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
      const courtDistrictNode = await loadDistrictSlice('congressional', 'nc_supreme_court_model', 2026);

      return {
        senateOptionText: options.us_senate_model_2026 || '',
        courtOptionText: options.nc_supreme_court_model_2026 || '',
        senateRows: senateRows.length,
        courtRows: courtRows.length,
        senateDemCandidate: String(senateRows[0]?.us_senate_model_dem_candidate || ''),
        senateRepCandidate: String(senateRows[0]?.us_senate_model_rep_candidate || ''),
        courtDemCandidate: String(courtRows[0]?.nc_supreme_court_model_dem_candidate || ''),
        courtRepCandidate: String(courtRows[0]?.nc_supreme_court_model_rep_candidate || ''),
        senateDistricts: Object.keys(senateDistrictNode?.general?.results || {}).length,
        courtDistricts: Object.keys(courtDistrictNode?.general?.results || {}).length
      };
    });

    expect(modeledSnapshot.senateOptionText).toBe('US Senate (2026) model');
    expect(modeledSnapshot.courtOptionText).toBe('NC Supreme Court Associate Justice Seat 1 (2026) Model');
    expect(modeledSnapshot.senateRows).toBeGreaterThan(2000);
    expect(modeledSnapshot.courtRows).toBeGreaterThan(2000);
    expect(modeledSnapshot.senateDemCandidate).toBe('Roy Cooper');
    expect(modeledSnapshot.senateRepCandidate).toBe('Michael Whatley');
    expect(modeledSnapshot.courtDemCandidate).toBe('Anita Earls');
    expect(modeledSnapshot.courtRepCandidate).toBe('Sarah Stevens');
    expect(modeledSnapshot.senateDistricts).toBeGreaterThan(0);
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
