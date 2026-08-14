const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const APP_READY_TIMEOUT = 180_000;
const SHOT_DIR = '/opt/cursor/artifacts/screenshots';

const DEM_MID_RAMP = [
  { label: 'Tilt', margin: 0.5, hex: '#c7ddf0' },
  { label: 'Lean', margin: 1, hex: '#9ecae1' },
  { label: 'Likely', margin: 5.5, hex: '#6baed6' },
  { label: 'Safe', margin: 10, hex: '#4795d2' },
  { label: 'Stronghold', margin: 20, hex: '#2876b5' },
  { label: 'Dominant', margin: 30, hex: '#08519c' },
  { label: 'Annihilation', margin: 40, hex: '#08306b' }
];

function relativeLuminance(hex) {
  const raw = String(hex || '').replace('#', '');
  const rgb = [0, 2, 4].map((i) => Number.parseInt(raw.slice(i, i + 2), 16) / 255);
  const linear = rgb.map((channel) => (
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  ));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

async function waitForAtlasReady(page) {
  await page.waitForSelector('#map .mapboxgl-canvas', { timeout: APP_READY_TIMEOUT });
  await page.waitForSelector('#contestSelect', { timeout: APP_READY_TIMEOUT });
  await page.waitForFunction(() => {
    const sel = document.getElementById('contestSelect');
    return !!(sel && Array.from(sel.options || []).some((option) => (option?.value || '').trim()));
  }, { timeout: APP_READY_TIMEOUT });
}

test('first-paint legend DEM spectrum is monotonic Lean → Likely → Safe', async ({ request }) => {
  const response = await request.get('/index.html');
  expect(response.ok()).toBeTruthy();
  const source = await response.text();
  const spectrum = source.match(/<div class="legend-spectrum margins">([\s\S]*?)<\/div>/);
  expect(spectrum).toBeTruthy();
  const hexes = [...spectrum[1].matchAll(/background:\s*(#[0-9a-fA-F]{6})/g)].map((row) => row[1].toLowerCase());
  expect(hexes).toHaveLength(15);
  expect(hexes.slice(8)).toEqual(DEM_MID_RAMP.map((stop) => stop.hex));

  const demLuminance = hexes.slice(8).map(relativeLuminance);
  for (let i = 1; i < demLuminance.length; i += 1) {
    expect(demLuminance[i], `${DEM_MID_RAMP[i].label} should be darker than ${DEM_MID_RAMP[i - 1].label}`).toBeLessThan(demLuminance[i - 1] - 0.02);
  }
});

test.describe('live Democratic margin ramp', () => {
  test.setTimeout(180_000);
  test.beforeEach(async ({ page }) => {
    await page.goto('/index.html');
    await waitForAtlasReady(page);
  });

  test('colorForMarginMode darkens steadily on the DEM side', async ({ page }) => {
    const live = await page.evaluate((stops) => (
      stops.map((stop) => ({
        label: stop.label,
        hex: String(colorForMarginMode(stop.margin, 'D') || '').toLowerCase()
      }))
    ), DEM_MID_RAMP);

    expect(live.map((stop) => stop.hex)).toEqual(DEM_MID_RAMP.map((stop) => stop.hex));

    const luminance = live.map((stop) => relativeLuminance(stop.hex));
    for (let i = 1; i < luminance.length; i += 1) {
      expect(
        luminance[i],
        `${live[i].label} (${live[i].hex}) should be darker than ${live[i - 1].label} (${live[i - 1].hex})`
      ).toBeLessThan(luminance[i - 1] - 0.02);
    }
  });

  test('2024 President counties paint DEM Likely darker than Lean and Safe darker than Likely', async ({ page }) => {
    await page.selectOption('#contestSelect', 'president_2024');
    await page.waitForFunction(() => (
      document.getElementById('contestSelect')?.value === 'president_2024' &&
      typeof lastCompletedContestSelection !== 'undefined' &&
      lastCompletedContestSelection === 'president_2024'
    ), { timeout: APP_READY_TIMEOUT });

    await page.waitForFunction(() => {
      try {
        const fill = map.getPaintProperty('county-fill', 'fill-color');
        return Array.isArray(fill) && fill[0] === 'match' && fill.includes('FORSYTH') && fill.includes('#4795d2');
      } catch (_) {
        return false;
      }
    }, { timeout: APP_READY_TIMEOUT });

    const painted = await page.evaluate(() => {
      const fill = map.getPaintProperty('county-fill', 'fill-color');
      const byName = {};
      if (Array.isArray(fill) && fill[0] === 'match') {
        for (let i = 2; i < fill.length - 1; i += 2) {
          byName[String(fill[i] || '').toUpperCase()] = String(fill[i + 1] || '').toLowerCase();
        }
      }
      return {
        pitt: byName.PITT || '',
        hoke: byName.HOKE || '',
        forsyth: byName.FORSYTH || '',
        warren: byName.WARREN || '',
        newHanover: byName['NEW HANOVER'] || '',
        live: {
          tilt: String(colorForMarginMode(0.5, 'D') || '').toLowerCase(),
          lean: String(colorForMarginMode(1, 'D') || '').toLowerCase(),
          likely: String(colorForMarginMode(5.5, 'D') || '').toLowerCase(),
          safe: String(colorForMarginMode(10, 'D') || '').toLowerCase()
        },
        legend: Array.from(document.querySelectorAll('#legend-content .legend-spectrum.margins .legend-segment'))
          .map((el) => {
            const bg = el.getAttribute('style') || el.style.background || getComputedStyle(el).backgroundColor;
            const match = String(bg).match(/#([0-9a-fA-F]{6})/);
            if (match) return `#${match[1].toLowerCase()}`;
            const rgb = String(bg).match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
            if (!rgb) return '';
            return `#${[1, 2, 3].map((i) => Number(rgb[i]).toString(16).padStart(2, '0')).join('')}`;
          })
      };
    });

    expect(painted.live).toEqual({
      tilt: '#c7ddf0',
      lean: '#9ecae1',
      likely: '#6baed6',
      safe: '#4795d2'
    });
    expect(painted.legend.slice(8)).toEqual(DEM_MID_RAMP.map((stop) => stop.hex));
    expect(painted.pitt).toBe('#6baed6');
    expect(painted.hoke).toBe('#6baed6');
    expect(painted.forsyth).toBe('#4795d2');
    expect(painted.warren).toBe('#4795d2');
    expect(painted.newHanover).toBe('#c7ddf0');
    expect(relativeLuminance(painted.live.likely)).toBeLessThan(relativeLuminance(painted.live.lean));
    expect(relativeLuminance(painted.live.safe)).toBeLessThan(relativeLuminance(painted.live.likely));

    await page.evaluate(() => {
      const help = document.getElementById('help-modal');
      if (help) help.style.display = 'none';
      const helpBackdrop = document.getElementById('help-backdrop');
      if (helpBackdrop) helpBackdrop.style.display = 'none';
      const overlay = document.getElementById('overlay-opacity-preset');
      if (overlay) {
        overlay.value = 'balanced';
        overlay.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    await page.waitForTimeout(600);

    fs.mkdirSync(SHOT_DIR, { recursive: true });
    await page.locator('#legend').screenshot({ path: path.join(SHOT_DIR, 'dem-ramp-legend.png') });
    await page.screenshot({ path: path.join(SHOT_DIR, 'dem-ramp-2024-president-counties.png'), fullPage: false });
  });
});
