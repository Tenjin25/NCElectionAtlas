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
    const hasRiggs = values.some((v) => v.startsWith('nc_supreme_court_associate_justice_seat_06_2024'));
    return hasPresident && hasRiggs;
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

test.describe('North Carolina Election Atlas regression checks', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/index.html');
    await waitForAtlasReady(page);
  });

  test('loads with no contest selected and reveal overlay default', async ({ page }) => {
    await expect(page.locator('#contestSelect')).toHaveValue('');
    await expect(page.locator('#overlay-opacity-preset')).toHaveValue('reveal');
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

  test('split-ticket toggle swaps President and Riggs contests', async ({ page }) => {
    await waitForSplitTicketOptions(page);

    const contestKeys = await page.evaluate(() => {
      const sel = document.getElementById('contestSelect');
      const values = Array.from(sel?.options || [])
        .map((opt) => (opt && opt.value ? String(opt.value).trim() : ''))
        .filter(Boolean);
      const presidentValue = values.find((v) => v.startsWith('president_2024')) || '';
      const riggsValue = values.find((v) => v.startsWith('nc_supreme_court_associate_justice_seat_06_2024')) || '';
      return { presidentValue, riggsValue };
    });

    expect(contestKeys.presidentValue).toBeTruthy();
    expect(contestKeys.riggsValue).toBeTruthy();

    await page.selectOption('#contestSelect', contestKeys.presidentValue);
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      contestKeys.presidentValue
    );

    await page.click('#split-ticket-toggle');
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      contestKeys.riggsValue
    );
    await expect(page.locator('#context-contest')).toContainText(/Supreme Court/i);

    await page.click('#split-ticket-toggle');
    await page.waitForFunction(
      (v) => document.getElementById('contestSelect')?.value === v,
      contestKeys.presidentValue
    );
    await expect(page.locator('#context-contest')).toContainText(/President/i);
  });

  test('precinct search selection sets yellow-highlight target and zooms in', async ({ page }) => {
    await page.click('#precinct-toggle');
    await page.waitForFunction(() => {
      const text = (document.getElementById('precinct-toggle')?.textContent || '').trim();
      return text === 'Precincts On' || text === 'Precincts Loading';
    });

    await page.getByRole('button', { name: 'Wake 01-14' }).first().click();

    await page.waitForFunction(() => {
      try {
        if (typeof selectedPrecinctNorm === 'undefined' || typeof map === 'undefined' || !map) return false;
        return /^WAKE - /i.test(String(selectedPrecinctNorm || '')) && Number(map.getZoom()) >= 9.8;
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });

    const selectedState = await page.evaluate(() => {
      const selected = typeof selectedPrecinctNorm === 'undefined' ? '' : String(selectedPrecinctNorm || '');
      const zoom = (typeof map !== 'undefined' && map && typeof map.getZoom === 'function') ? Number(map.getZoom()) : 0;
      const searchValue = String(document.getElementById('county-search')?.value || '').trim();
      return { selected, zoom, searchValue };
    });

    expect(selectedState.selected).toMatch(/^WAKE - /i);
    expect(selectedState.zoom).toBeGreaterThanOrEqual(9.8);
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

    await page.click('#precinct-toggle');
    await page.waitForFunction(() => {
      const text = (document.getElementById('precinct-toggle')?.textContent || '').trim();
      return text === 'Precincts On' || text === 'Precincts Loading';
    }, { timeout: APP_READY_TIMEOUT });

    await page.getByRole('button', { name: 'Wake 01-14' }).first().click();
    await page.waitForFunction(() => {
      try {
        if (typeof selectedPrecinctNorm === 'undefined' || typeof map === 'undefined' || !map) return false;
        return /^WAKE - /i.test(String(selectedPrecinctNorm || '')) && Number(map.getZoom()) >= 9.8;
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });

    const clickHandle = await page.waitForFunction(() => {
      try {
        if (typeof map === 'undefined' || !map || typeof selectedPrecinctNorm === 'undefined') return null;
        const norm = String(selectedPrecinctNorm || '').trim().toUpperCase();
        if (!norm) return null;

        const src = map.getSource('precinct-centroids');
        const gj = src ? (src._data || src.data) : null;
        const features = gj?.features || [];
        const hit = features.find((f) => String(f?.properties?.precinct_norm || '').trim().toUpperCase() === norm);
        const coords = hit?.geometry?.coordinates;
        if (!Array.isArray(coords) || coords.length < 2) return null;

        const projected = map.project(coords);
        if (!projected) return null;
        const layers = ['precinct-fill', 'precinct-dot', 'precinct-dot-missing'].filter((id) => map.getLayer(id));
        if (!layers.length) return null;
        const rendered = map.queryRenderedFeatures([projected.x, projected.y], { layers });
        if (!rendered || !rendered.length) return null;
        const container = map.getContainer && map.getContainer();
        const rect = container && container.getBoundingClientRect ? container.getBoundingClientRect() : null;
        if (!rect) return null;
        return {
          x: Math.round(rect.left + projected.x),
          y: Math.round(rect.top + projected.y)
        };
      } catch (_) {
        return null;
      }
    }, { timeout: APP_READY_TIMEOUT });
    const clickPoint = await clickHandle.jsonValue();
    expect(clickPoint && Number.isFinite(clickPoint.x) && Number.isFinite(clickPoint.y)).toBeTruthy();

    const pinnedFromSelection = await page.evaluate(() => {
      try {
        if (typeof map === 'undefined' || !map || typeof selectedPrecinctNorm === 'undefined') return false;
        const norm = String(selectedPrecinctNorm || '').trim().toUpperCase();
        if (!norm) return false;
        const layers = ['precinct-fill', 'precinct-dot', 'precinct-dot-missing'].filter((id) => map.getLayer(id));
        if (!layers.length) return false;

        const src = map.getSource('precinct-centroids');
        const gj = src ? (src._data || src.data) : null;
        const features = gj?.features || [];
        const hit = features.find((f) => String(f?.properties?.precinct_norm || '').trim().toUpperCase() === norm);
        const coords = hit?.geometry?.coordinates;
        if (!Array.isArray(coords) || coords.length < 2) return false;

        const projected = map.project(coords);
        if (!projected) return false;
        const rendered = map.queryRenderedFeatures([projected.x, projected.y], { layers });
        const feature = rendered && rendered.length ? rendered[0] : null;
        if (!feature || typeof renderPrecinctHoverAtPoint !== 'function') return false;

        renderPrecinctHoverAtPoint(
          { x: projected.x, y: projected.y },
          feature,
          { forceTooltip: true, pinSelection: true }
        );
        return true;
      } catch (_) {
        return false;
      }
    });
    expect(pinnedFromSelection).toBeTruthy();

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
