const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasModeling = require('../js/atlas-modeling.js');

test('builds stable modeled-definition signatures independent of key order', () => {
  const first = {
    year: 2026,
    contestType: 'us_senate_model',
    weights: { recent: 0.6, baseline: 0.4 }
  };
  const second = {
    weights: { baseline: 0.4, recent: 0.6 },
    contestType: 'us_senate_model',
    year: 2026
  };

  assert.equal(
    AtlasModeling.getDefinitionSignature(first),
    AtlasModeling.getDefinitionSignature(second)
  );
  assert.equal(AtlasModeling.getDefinitionSignature({ year: 2026 }), '');
});

test('serializes non-finite and circular model inputs deterministically', () => {
  const input = { uncertainty: Number.POSITIVE_INFINITY };
  input.self = input;

  assert.equal(
    AtlasModeling.stableStringify(input),
    '{"self":"[Circular]","uncertainty":"Infinity"}'
  );
});

test('returns model county-behavior labels with a balanced fallback', () => {
  assert.equal(AtlasModeling.getCountyBehaviorLabel('rural_surge'), 'Rural surge');
  assert.equal(AtlasModeling.getCountyBehaviorLabel('unknown'), 'Balanced counties');
});

test('classifies model confidence from tuning distance and behavior', () => {
  const baseline = {
    blendWeight: 0.6,
    turnoutFactor: 1,
    candidateBonusScale: 1,
    countyBehaviorMode: 'balanced',
    uncertaintyBoost: 1
  };

  assert.deepEqual(
    AtlasModeling.inferConfidence({ ...baseline }, baseline),
    { label: 'High', range: '\u00b11.4 pts' }
  );
  assert.deepEqual(
    AtlasModeling.inferConfidence({
      blendWeight: 1.2,
      turnoutFactor: 1.8,
      candidateBonusScale: 2,
      countyBehaviorMode: 'volatile',
      uncertaintyBoost: 2
    }, baseline),
    { label: 'Low', range: '\u00b13.0 pts' }
  );
  assert.deepEqual(
    AtlasModeling.inferConfidence(null, baseline),
    { label: 'Low', range: '\u00b12.0 pts' }
  );
});

const dependencies = {
  shiftVotes(dem, rep, other, total, swing) {
    return { dem: dem + swing, rep: rep - swing, other, total };
  },
  rescaleVotes(votes, total) {
    return { ...votes, total };
  },
  signedMargin(dem, rep, total) {
    return total > 0 ? ((rep - dem) / total) * 100 : 0;
  },
  colorForMargin(margin, winner) {
    return `${winner}:${margin.toFixed(1)}`;
  }
};

test('aggregates statewide margins from modeled district results', () => {
  assert.equal(
    AtlasModeling.computeStatewideMarginFromDistrictResults({
      1: { dem_votes: 40, rep_votes: 60, total_votes: 100 },
      2: { dem_votes: 55, rep_votes: 45, total_votes: 100 }
    }, dependencies.signedMargin),
    5
  );
});

test('builds modeled contest rows with candidate metadata', () => {
  const row = AtlasModeling.buildContestRow({
    county: 'WAKE - 01',
    president_dem: 40,
    president_rep: 50,
    president_other: 10,
    president_total: 100
  }, {
    year: 2026,
    baseContestType: 'president',
    contestType: 'us_senate_model',
    demCandidate: 'Dem Candidate',
    repCandidate: 'Rep Candidate'
  }, 5, {
    targetTotal: 120,
    modelMeta: {
      baselineNoCandidateSigned: 8,
      desiredSigned: 2,
      candidateEffectDemPts: 6,
      explanationTags: ['candidate strength', '', 'turnout']
    }
  }, dependencies);

  assert.equal(row.us_senate_model_dem, 45);
  assert.equal(row.us_senate_model_rep, 45);
  assert.equal(row.us_senate_model_total, 120);
  assert.equal(row.us_senate_model_winner, 'TIE');
  assert.equal(row.us_senate_model_color, '#9ca3af');
  assert.equal(row.__model_candidate_effect_d_pts, 6);
  assert.equal(row.__model_explain_tags, 'candidate strength \u2022 turnout');
});

test('builds modeled district rows while retaining source metadata', () => {
  const row = AtlasModeling.buildDistrictResultRow({
    district: 4,
    dem_votes: 40,
    rep_votes: 60,
    other_votes: 0,
    total_votes: 100,
    competitiveness: { label: 'old' }
  }, {
    demCandidate: 'D',
    repCandidate: 'R'
  }, 5, 100, dependencies);

  assert.equal(row.district, 4);
  assert.equal(row.dem_votes, 45);
  assert.equal(row.rep_votes, 55);
  assert.equal(row.winner, 'REP');
  assert.equal(row.competitiveness.label, 'old');
  assert.equal(row.competitiveness.color, 'R:10.0');
});

test('reaggregates modeled precincts and allocates non-geographic votes by party', () => {
  const contestType = 'us_senate_model';
  const row = (county, dem, rep) => ({
    county,
    [`${contestType}_dem`]: dem,
    [`${contestType}_rep`]: rep,
    [`${contestType}_other`]: 0,
    [`${contestType}_total`]: dem + rep
  });
  const crosswalk = new Map([
    ['ALPHA - 01', [{ districtNum: '1', weight: 1 }]],
    ['ALPHA - 02', [{ districtNum: '2', weight: 1 }]],
    ['BETA - OLD 1', [{ districtNum: '3', weight: 1 }]],
    ['BETA - OLD 2', [{ districtNum: '4', weight: 1 }]]
  ]);

  const aggregate = AtlasModeling.aggregatePrecinctRowsToDistricts([
    row('ALPHA - 01', 80, 20),
    row('ALPHA - 02', 20, 80),
    row('ALPHA - ONESTOP', 10, 10),
    row('BETA - NEW', 40, 60)
  ], crosswalk, {
    contestType,
    demCandidate: 'D',
    repCandidate: 'R',
    referenceResults: {
      3: { dem_votes: 30, rep_votes: 70 },
      4: { dem_votes: 70, rep_votes: 30 }
    }
  });

  assert.ok(aggregate);
  assert.equal(aggregate.results['1'].dem_votes, 88);
  assert.equal(aggregate.results['1'].rep_votes, 22);
  assert.equal(aggregate.results['2'].dem_votes, 22);
  assert.equal(aggregate.results['2'].rep_votes, 88);
  assert.equal(aggregate.results['3'].dem_votes, 12);
  assert.equal(aggregate.results['3'].rep_votes, 42);
  assert.equal(aggregate.results['4'].dem_votes, 28);
  assert.equal(aggregate.results['4'].rep_votes, 18);
  assert.ok(aggregate.results['4'].margin_pct < 0);
  assert.equal(aggregate.results['4'].margin, -10);
  assert.equal(aggregate.results['4'].winner, 'DEM');
  assert.deepEqual(aggregate.diagnostics, {
    matchedPrecinctRows: 2,
    allocatedNongeographicRows: 2,
    referenceFallbackCounties: ['BETA'],
    totalPrecinctRows: 4,
    matchCoveragePct: 100
  });
});
