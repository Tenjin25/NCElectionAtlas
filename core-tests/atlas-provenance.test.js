const test = require('node:test');
const assert = require('node:assert/strict');
const provenance = require('../js/atlas-provenance.js');

test('identifies official district benchmarks as highest-confidence sources', () => {
  const result = provenance.describeProvenance({
    source: 'batch_shatter_vap_party_split',
    match_coverage_pct: 99.66,
    ncga_statpack_calibrated: true,
    district_lines_label: '2022 lines'
  }, { kind: 'district' });
  assert.equal(result.level, 'high');
  assert.equal(result.label, 'Official benchmark');
  assert.equal(result.coverage, 99.66);
});

test('distinguishes certified county totals from geographic estimates', () => {
  const result = provenance.describeProvenance({ source: 'county_totals' }, { kind: 'county', hasOfficialCountyTotal: true });
  assert.equal(result.level, 'high');
  assert.equal(result.label, 'Certified total');
});

test('does not label a county aggregate as certified without a county total', () => {
  const result = provenance.describeProvenance({ source: 'batch_shatter_vap_party_split' }, { kind: 'county' });
  assert.notEqual(result.label, 'Certified total');
});

test('warns when a precinct is displaying a county fallback', () => {
  const result = provenance.describeProvenance({}, {
    kind: 'precinct',
    rowMeta: { __fallback_scope: 'county' }
  });
  assert.equal(result.level, 'low');
  assert.equal(result.label, 'County fallback');
});

test('labels modeled contests without implying certified accuracy', () => {
  const result = provenance.describeProvenance({}, { kind: 'county', modeled: true });
  assert.equal(result.level, 'modeled');
  assert.match(result.summary, /not a certified election result/i);
});

test('warns for estimated comparisons and leaves exact comparisons unqualified', () => {
  const exact = provenance.describeProvenance({}, { kind: 'county', hasOfficialCountyTotal: true });
  const estimated = provenance.describeProvenance({ match_coverage_pct: 99.1 }, { kind: 'district' });
  assert.equal(provenance.comparisonCaution(exact, exact), '');
  assert.match(provenance.comparisonCaution(exact, estimated), /geographic allocation/);
});
