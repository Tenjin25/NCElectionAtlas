const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasRegions = require('../js/atlas-regions.js');

test('normalizes region county names and removes a County suffix', () => {
  assert.equal(AtlasRegions.normalizeCountyName('New Hanover County'), 'NEW HANOVER');
  assert.equal(AtlasRegions.normalizeCountyName("Wake's"), 'WAKES');
  assert.deepEqual(
    AtlasRegions.getCountySet(['Wake', 'Durham County', '', null]),
    new Set(['WAKE', 'DURHAM'])
  );
});

test('aggregates only the requested regional counties across precinct rows', () => {
  const rows = [
    {
      county: 'WAKE - 01-01',
      president_dem: 60,
      president_rep: 35,
      president_other: 5,
      president_total: 100,
      president_dem_candidate: 'Joseph R. Biden',
      president_rep_candidate: 'Donald J. Trump'
    },
    {
      county: 'WAKE - 01-02',
      president_dem: 40,
      president_rep: 50,
      president_other: 10,
      president_total: 100
    },
    {
      county: 'DURHAM - 01',
      president_dem: 80,
      president_rep: 15,
      president_other: 5,
      president_total: 100
    },
    {
      county: 'MECKLENBURG - 001',
      president_dem: 70,
      president_rep: 25,
      president_other: 5,
      president_total: 100
    }
  ];

  assert.deepEqual(
    AtlasRegions.aggregateContestRows(rows, 'president', ['Wake', 'Durham']),
    {
      dem: 180,
      rep: 100,
      other: 20,
      total: 300,
      demCandidate: 'Joseph R. Biden',
      repCandidate: 'Donald J. Trump',
      matchedCounties: 2,
      totalCounties: 2
    }
  );
});

test('reports unmatched configured counties without adding votes', () => {
  assert.deepEqual(
    AtlasRegions.aggregateContestRows([], 'governor', ['Wake', 'Durham']),
    {
      dem: 0,
      rep: 0,
      other: 0,
      total: 0,
      demCandidate: '',
      repCandidate: '',
      matchedCounties: 0,
      totalCounties: 2
    }
  );
});

test('uses certified county totals when a regional precinct sum differs', () => {
  const rows = [{ county: 'WAKE - 01', president_dem: 40, president_rep: 30, president_other: 2, president_total: 72 }];
  Object.defineProperty(rows, '__officialCountyTotals', {
    value: { WAKE: { dem_votes: 50, rep_votes: 35, other_votes: 3, total_votes: 88 } }
  });
  const region = AtlasRegions.aggregateContestRows(rows, 'president', ['Wake']);
  assert.equal(region.dem, 50);
  assert.equal(region.rep, 35);
  assert.equal(region.total, 88);
});
