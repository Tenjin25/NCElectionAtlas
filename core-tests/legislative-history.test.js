const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const HISTORY_DIR = path.join(ROOT, 'data', 'legislative_history');

test('legislative history stays separate in data and follows the active chamber picker', () => {
  const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
  assert.match(html, /if \(!\['state_house', 'state_senate'\]\.includes\(currentView\)\) return/);
  assert.match(html, /State Senate' : 'State House'} history — modern-lines estimates/);
  assert.match(html, /const chamber = isSenate \? 'state_senate' : 'state_house'/);
  assert.match(html, /option\.value = `legislative_history_\$\{chamber\}_\$\{year\}`/);
  assert.doesNotMatch(html, /id="legislative-history-panel"/);
  assert.match(html, /context: 'votehub-results'/);
  assert.match(html, /Historical candidate lineage/);
  assert.ok(
    fs.existsSync(path.join(ROOT, 'scripts', 'build_legislative_history_crosswalks.py')),
    'standalone history builder should exist'
  );
});

test('legislative history manifest covers both chambers, 2000-2020, and both modern plans', () => {
  const manifestPath = path.join(HISTORY_DIR, 'manifest.json');
  assert.ok(fs.existsSync(manifestPath), 'history manifest should be generated');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const files = manifest.files || [];
  assert.equal(files.length, 44);

  const years = new Set(files.map(entry => Number(entry.year)));
  assert.deepEqual(
    [...years].sort((a, b) => a - b),
    [2000, 2002, 2004, 2006, 2008, 2010, 2012, 2014, 2016, 2018, 2020]
  );
  assert.deepEqual(
    [...new Set(files.map(entry => entry.chamber))].sort(),
    ['state_house', 'state_senate']
  );
  assert.deepEqual(
    [...new Set(files.map(entry => Number(entry.target_lines_year)))].sort(),
    [2022, 2024]
  );
});

test('generated history slices expose lineage and honest coverage metadata', () => {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(HISTORY_DIR, 'manifest.json'), 'utf8')
  );
  for (const entry of manifest.files || []) {
    const filePath = path.join(HISTORY_DIR, entry.file);
    assert.ok(fs.existsSync(filePath), `missing ${entry.file}`);
    const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const rawPayload = fs.readFileSync(filePath, 'utf8');
    assert.equal(payload.schema, 'nc_legislative_history.v1');
    assert.match(rawPayload, /^\{\r?\n  "/, `${entry.file} should be pretty-printed`);
    assert.ok(rawPayload.endsWith('\n'), `${entry.file} should end with a newline`);
    assert.equal(payload.meta.interpretation, 'party_vote_composite_on_modern_geometry');
    assert.match(payload.meta.source_plan.block_assignment_url, /^https:\/\/www\.ncleg\.gov\//);
    assert.ok(payload.meta.source_race_count > 0);
    assert.ok(payload.meta.contested_source_race_count > 0);
    assert.ok(payload.meta.match_coverage_pct >= 0 && payload.meta.match_coverage_pct <= 100);
    assert.ok(payload.meta.allocated_vote_coverage_pct >= 0);
    assert.ok(
      payload.source_races.some(race => race.dem_candidate || race.rep_candidate),
      `${entry.file} should retain candidate names when available`
    );
    assert.ok(
      payload.source_races.every(race => Array.isArray(race.candidates) && race.candidates.length),
      `${entry.file} should retain the complete candidate slate`
    );
    assert.ok(
      payload.source_races.every(race =>
        race.candidates.every(candidate =>
          candidate.name === candidate.name.trim() &&
          !/\s{2,}/.test(candidate.name) &&
          !/\(\s*replacement\s+for\b/i.test(candidate.name)
        )
      ),
      `${entry.file} should contain cleaned candidate display names`
    );
    if (Number(payload.year) === 2020 && payload.chamber === 'state_senate') {
      const names = payload.source_races.flatMap(race => race.candidates.map(candidate => candidate.name));
      assert.ok(names.includes('Ernestine Bazemore'));
      assert.ok(!names.includes('Ernestine (Byrd) Bazemore'));
    }
    for (const race of payload.source_races) {
      for (const candidate of race.candidates || []) {
        assert.equal(candidate.name, candidate.name.trim(), `${entry.file} has padded candidate whitespace`);
        assert.doesNotMatch(candidate.name, /\s{2,}/, `${entry.file} has repeated candidate whitespace`);
        assert.doesNotMatch(
          candidate.name,
          /\(\s*replacement\s+for\b/i,
          `${entry.file} includes ballot metadata in a candidate name`
        );
      }
    }
    if (Number(payload.year) === 2000) {
      const seatTotal = payload.source_races.reduce((sum, race) => sum + Number(race.seats || 0), 0);
      assert.equal(seatTotal, expectedDistrictSeatTotal(payload.chamber));
      assert.ok(payload.source_races.some(race => Number(race.seats) > 1));
    }

    const expectedDistricts = payload.chamber === 'state_house' ? 120 : 50;
    const results = payload.general?.results || {};
    assert.equal(Object.keys(results).length, expectedDistricts);
    for (const row of Object.values(results)) {
      assert.ok(row.contested_vote_coverage_pct >= 0 && row.contested_vote_coverage_pct <= 100);
      assert.ok(Array.isArray(row.source_districts));
      for (const source of row.source_districts) {
        assert.ok(Number(source.seats) >= 1);
        assert.ok(Array.isArray(source.candidates) && source.candidates.length);
        assert.ok(source.candidates.every(candidate => candidate.name && candidate.party));
      }
    }
  }
});

function expectedDistrictSeatTotal(chamber) {
  return chamber === 'state_house' ? 120 : 50;
}
