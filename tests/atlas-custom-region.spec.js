const { test, expect } = require('@playwright/test');
const presidential2024 = require('../data/contests/president_2024.json');

test('custom county region can be saved and shared', async ({ page }) => {
  test.setTimeout(180_000);
  await page.addInitScript(() => {
    window.__statusLog = [];
    document.addEventListener('DOMContentLoaded', () => {
      const element = document.getElementById('status-message');
      if (element) new MutationObserver(() => window.__statusLog.push(element.textContent))
        .observe(element, { childList: true, characterData: true, subtree: true });
    });
  });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('requestfailed', request => {
    errors.push(`${request.url()}: ${request.failure()?.errorText}`);
  });
  await page.goto('/index.html', { waitUntil: 'commit', timeout: 30000 });
  await page.waitForFunction(() => document.querySelectorAll('#custom-region-counties input').length === 100, null, { timeout: 120000 })
    .catch(async () => {
      const state = await page.evaluate(() => ({
        readyState: document.readyState,
        onload: typeof window.onload,
        mapLoaded: typeof map !== 'undefined' && map.loaded(),
        appReady: typeof appReady !== 'undefined' && appReady,
        initError: window.__atlasInitError,
        initTail: (() => { try { return atlasInitStarted; } catch (error) { return error.message; } })(),
        initFunction: typeof startAtlasOnce,
        countySource: !!map.getSource('counties'),
        countyNames: Object.keys(countyNameMap || {}).length,
        contestOptions: document.querySelectorAll('#contestSelect option').length,
        customRegionGeoJSON: !!customRegionGeoJSON,
        resourceCount: performance.getEntriesByType('resource').length,
        feedback: document.getElementById('custom-region-feedback')?.textContent,
        status: document.getElementById('status-message')?.textContent,
        statusLog: window.__statusLog
      })).catch(error => ({ evaluateError: error.message }));
      throw new Error(`County controls did not load: ${JSON.stringify(state)}; ${errors.slice(0, 5).join(' | ')}`);
    });
  await page.waitForFunction(() => [...document.querySelectorAll('#contestSelect option')].some(option => option.value === 'president_2024'), null, { timeout: 120000 });
  await page.selectOption('#contestSelect', 'president_2024');
  await expect(page.locator('.region-jump-group:not([hidden]) .region-jump-group-label')).toHaveText(['Metro areas', 'Regions', 'Corridors']);
  const presets = await page.evaluate(() => Object.entries(REGION_JUMPS)
    .filter(([key]) => key !== 'custom')
    .map(([key, region]) => ({ key, bounds: region.bounds, countyCount: region.counties.length })));
  expect(presets).toHaveLength(13);
  expect(presets.every(region => Array.isArray(region.bounds) && region.bounds.length === 2)).toBeTruthy();
  expect(presets.find(region => region.key === 'i95').bounds).toEqual([[-79.461506, 34.299342], [-77.066194, 36.54728]]);
  expect(presets.find(region => region.key === 'mountains').bounds).toEqual([[-84.321821, 34.986628], [-80.868746, 36.588137]]);
  expect(presets.find(region => region.key === 'southeast').countyCount).toBe(12);
  await page.locator('[data-region-jump="southeast"]').click();
  await page.waitForFunction(() => voteCounterPinned?.meta?.regionKey === 'southeast', null, { timeout: 30000 });
  const southeast = await page.evaluate(() => ({
    counties: REGION_JUMPS.southeast.counties,
    pinned: voteCounterPinned
  }));
  for (const [actual, sourceKey] of [['demVotes', 'dem_votes'], ['repVotes', 'rep_votes'], ['otherVotes', 'other_votes']]) {
    expect(southeast.pinned[actual]).toBe(southeast.counties.reduce((sum, county) => (
      sum + presidential2024.county_totals[county.toUpperCase()][sourceKey]
    ), 0));
  }
  await page.locator('#custom-region-builder').evaluate(element => { element.open = true; });
  await page.fill('#custom-region-name', 'Triangle test');
  await page.locator('#custom-region-counties input[value="WAKE"]').check();
  await page.locator('#custom-region-counties input[value="DURHAM"]').check();
  await page.click('#custom-region-save');
  await expect(page.locator('#custom-region-jump')).toHaveText('Triangle test');
  await expect(page.locator('#custom-region-feedback')).toContainText('2 counties saved');
  await page.waitForFunction(() => voteCounterPinned?.meta?.regionKey === 'custom', null, { timeout: 30000 });
  const state = await page.evaluate(() => ({
    stored: JSON.parse(localStorage.getItem('atlasCustomCountyRegionV1') || 'null'),
    link: collectURLStateFromUI().toString(),
    region: REGION_JUMPS.custom,
    pinned: voteCounterPinned
  }));
  expect(state.stored).toEqual({ label: 'Triangle test', counties: ['DURHAM', 'WAKE'] });
  expect(state.region.bounds).toEqual([[-79.016305, 35.519458], [-78.253711, 36.23932]]);
  for (const [actual, sourceKey] of [['demVotes', 'dem_votes'], ['repVotes', 'rep_votes'], ['otherVotes', 'other_votes']]) {
    expect(state.pinned[actual]).toBe(
      presidential2024.county_totals.DURHAM[sourceKey] + presidential2024.county_totals.WAKE[sourceKey]
    );
  }
  expect(state.link).toContain('rcounties=DURHAM%2CWAKE');
  await page.evaluate(async query => {
    localStorage.removeItem('atlasCustomCountyRegionV1');
    delete REGION_JUMPS.custom;
    voteCounterPinned = null;
    document.getElementById('custom-region-jump').hidden = true;
    history.pushState(null, '', `?${query}`);
    await restoreUIState();
  }, state.link);
  await page.waitForFunction(() => voteCounterPinned?.meta?.regionKey === 'custom', null, { timeout: 30000 });
  await expect(page.locator('#custom-region-jump')).toHaveText('Triangle test');
  await expect(page.locator('#custom-region-counties input[value="WAKE"]')).toBeChecked();
  await expect(page.locator('#custom-region-counties input[value="DURHAM"]')).toBeChecked();
});
