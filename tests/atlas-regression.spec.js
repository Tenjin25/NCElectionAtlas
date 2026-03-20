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
