const { test, expect } = require('@playwright/test');

test('atlas ships Regular + Bold only so cached Manrope matches incognito weighting', async ({ request }) => {
  const response = await request.get('/index.html');
  expect(response.ok()).toBeTruthy();
  const source = await response.text();

  expect(source).toContain('family=Manrope:wght@400;700');
  expect(source).toContain('family=IBM+Plex+Sans:wght@400;700');
  expect(source).not.toContain('Manrope:wght@500;600;700;800');
  expect(source).toMatch(/font-synthesis:\s*none/);
  expect(source).toMatch(/const APP_BUILD_ID = '2026-08-14-incognito-text-weights-v1'/);
});
