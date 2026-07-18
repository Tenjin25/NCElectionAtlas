const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasData = require('../js/atlas-data.js');

test('resolves local and GitHub Pages base paths', () => {
  assert.equal(
    AtlasData.detectBasePath({ hostname: 'example.github.io', pathname: '/NCPrecinctMap/index.html' }),
    '/NCPrecinctMap'
  );
  assert.equal(AtlasData.detectBasePath({ hostname: 'localhost', pathname: '/app/index.html' }), '');
  assert.equal(
    AtlasData.withBase('./data/file.json', {
      hostname: 'example.github.io',
      pathname: '/NCPrecinctMap/index.html'
    }),
    '/NCPrecinctMap/data/file.json'
  );
  assert.equal(
    AtlasData.withBase('https://cdn.example.com/file.json', {}),
    'https://cdn.example.com/file.json'
  );
});

test('builds absolute and cache-busted resource URLs', () => {
  assert.equal(
    AtlasData.toAbsoluteUrl('data/file.json', 'https://example.com/app/index.html'),
    'https://example.com/app/data/file.json'
  );
  assert.equal(AtlasData.withCacheBuster('data/file.json', 'build 1'), 'data/file.json?v=build%201');
  assert.equal(AtlasData.withCacheBuster('data/file.json?x=1', '2'), 'data/file.json?x=1&v=2');
  assert.equal(AtlasData.withCacheBuster('mapbox://tileset', '2'), 'mapbox://tileset');
  assert.equal(AtlasData.withCacheBuster('data/file.json?v=old', '2'), 'data/file.json?v=old');
});

test('retries transient fetch failures without retrying permanent responses', async () => {
  const transientCalls = [];
  const transientResponse = await AtlasData.fetchWithRetry('/data/file.json', { cache: 'force-cache' }, {
    retryDelayMs: 0,
    fetcher: async (_input, init) => {
      transientCalls.push(init.cache);
      return transientCalls.length < 3
        ? { ok: false, status: 503 }
        : { ok: true, status: 200 };
    }
  });
  assert.equal(transientResponse.status, 200);
  assert.deepEqual(transientCalls, ['force-cache', 'reload', 'reload']);

  let permanentCalls = 0;
  const permanentResponse = await AtlasData.fetchWithRetry('/data/missing.json', {}, {
    retryDelayMs: 0,
    fetcher: async () => {
      permanentCalls += 1;
      return { ok: false, status: 404 };
    }
  });
  assert.equal(permanentResponse.status, 404);
  assert.equal(permanentCalls, 1);
});

test('deduplicates in-flight loads and retains resolved values', async () => {
  const resolvedCache = new Map();
  const inflightCache = new Map();
  let calls = 0;
  const load = async () => {
    calls += 1;
    await Promise.resolve();
    return { ok: true };
  };
  const options = { resolvedCache, inflightCache, load };
  const [first, second] = await Promise.all([
    AtlasData.loadCached('resource', options),
    AtlasData.loadCached('resource', options)
  ]);
  const third = await AtlasData.loadCached('resource', options);

  assert.strictEqual(first, second);
  assert.strictEqual(second, third);
  assert.equal(calls, 1);
  assert.equal(inflightCache.size, 0);
});

test('does not retain values rejected by the cache policy', async () => {
  const resolvedCache = new Map();
  let calls = 0;
  const options = {
    resolvedCache,
    inflightCache: new Map(),
    load: async () => 'large',
    shouldCache: () => false
  };
  await AtlasData.loadCached('resource', {
    ...options,
    load: async () => {
      calls += 1;
      return 'large';
    }
  });
  await AtlasData.loadCached('resource', {
    ...options,
    load: async () => {
      calls += 1;
      return 'large';
    }
  });
  assert.equal(calls, 2);
  assert.equal(resolvedCache.size, 0);
});

test('maps compact contest payloads to atlas row keys', () => {
  assert.deepEqual(
    AtlasData.mapContestPayloadRows({
      rows: [{
        county: 'WAKE - 01',
        dem_votes: 10,
        rep_votes: 12,
        other_votes: 1,
        total_votes: 23,
        dem_candidate: 'D',
        rep_candidate: 'R',
        margin: 2,
        margin_pct: 8.7,
        winner: 'REP',
        color: '#f00'
      }]
    }, 'governor', 2024),
    [{
      year: 2024,
      county: 'WAKE - 01',
      governor_dem: 10,
      governor_rep: 12,
      governor_other: 1,
      governor_total: 23,
      governor_dem_candidate: 'D',
      governor_rep_candidate: 'R',
      governor_margin: 2,
      governor_margin_pct: 8.7,
      governor_winner: 'REP',
      governor_color: '#f00'
    }]
  );
});
