const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasManifest = require('../js/atlas-manifest.js');

test('filters empty and uncontested statewide manifest entries', () => {
  const entries = [
    { contest_type: 'president', year: 2024, rows: 100, major_party_contested: false },
    { contest_type: 'governor', year: 2024, rows: 100, major_party_contested: false },
    {
      contest_type: 'nc_supreme_court_associate_justice_seat_06',
      year: 2024,
      rows: 100,
      dem_total: 0,
      rep_total: 10
    },
    { contest_type: 'attorney_general', year: 2024, rows: 100, major_party_contested: 'yes' },
    { contest_type: 'auditor', year: 2024, rows: 0, major_party_contested: true }
  ];

  assert.deepEqual(
    AtlasManifest.getVisibleManifestEntries(entries).map(entry => entry.contest_type),
    ['president', 'attorney_general']
  );
});

test('filters stale judicial district slices that have no statewide contest', () => {
  const districtEntries = [
    {
      contest_type: 'nc_court_of_appeals_judge_martin_seat',
      year: 2008,
      scope: 'congressional',
      districts: 14
    },
    {
      contest_type: 'nc_court_of_appeals_judge_arrowood_seat',
      year: 2008,
      scope: 'congressional',
      districts: 14
    },
    { contest_type: 'governor', year: 2008, scope: 'congressional', districts: 14 }
  ];
  const statewideEntries = [
    {
      // The statewide side may use the modern numbered name while an older
      // district slice retains the historical named-seat form.
      contest_type: 'nc_court_of_appeals_judge_seat_12',
      year: 2008,
      rows: 2700,
      major_party_contested: true
    }
  ];

  assert.deepEqual(
    AtlasManifest.getVisibleManifestEntries(districtEntries, statewideEntries)
      .map(entry => entry.contest_type),
    ['nc_court_of_appeals_judge_arrowood_seat', 'governor']
  );
});

test('maps named and numbered judicial contests into stable seat families', () => {
  assert.equal(
    AtlasManifest.getJudicialSeatFamilyKey(
      'nc_supreme_court_associate_justice_beasley_seat',
      2014
    ),
    'sc:4'
  );
  assert.equal(
    AtlasManifest.getJudicialSeatFamilyKey(
      'nc_supreme_court_associate_justice_seat_04',
      2022
    ),
    'sc:4'
  );
  assert.equal(
    AtlasManifest.getJudicialSeatFamilyKey('nc_court_of_appeals_judge_hunter_seat', 2016),
    'coa:13'
  );
  assert.equal(
    AtlasManifest.getJudicialSeatFamilyKey('nc_court_of_appeals_judge_hunter_seat', 2008),
    'coa:8'
  );
});

test('lists a judicial family and selects the nearest earlier election', () => {
  const manifest = [
    {
      year: 2006,
      contest_type: 'nc_supreme_court_associate_justice_seat_04',
      file: '2006.json'
    },
    {
      year: 2014,
      contest_type: 'nc_supreme_court_associate_justice_beasley_seat',
      file: '2014.json'
    },
    {
      year: 2022,
      contest_type: 'nc_supreme_court_associate_justice_seat_04',
      file: '2022.json'
    },
    { year: 2020, contest_type: 'governor', file: 'governor.json' }
  ];
  const family = AtlasManifest.listJudicialFamilyManifestEntries('sc:4', manifest);

  assert.deepEqual(family.map(entry => entry.year), [2006, 2014, 2022]);
  assert.equal(AtlasManifest.pickPriorJudicialFamilyEntry(family, 2022).year, 2014);
  assert.equal(AtlasManifest.pickPriorJudicialFamilyEntry(family, 2006), null);
});
