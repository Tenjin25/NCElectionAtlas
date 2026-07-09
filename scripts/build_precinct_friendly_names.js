/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

function toTitleCaseName(raw) {
  const s = String(raw || '').trim().toLowerCase();
  if (!s) return '';
  return s.replace(/\b([a-z])/g, (m, c) => c.toUpperCase());
}

function formatDisplayName(raw) {
  let s = toTitleCaseName(raw);
  if (!s) return '';
  s = s.replace(/\bSt (?=[A-Z])/g, 'St. ');
  return s;
}

function applyManualOverrides(counties) {
  const overrides = {
    ALLEGHANY: {
      '01': 'Cherry Lane',
      '03A': 'Gap Civil',
      '04': 'Glade Creek',
      '06A': 'Prathers Creek'
    },
    BEAUFORT: {
      GILEA: 'Gilead'
    },
    BERTIE: {
      RX: 'Roxobel',
      SN: 'Snakebite',
      WD: 'Woodville',
      WH: 'Whites'
    },
    CARTERET: {
      BCRK: 'Broad Creek',
      ISLE: 'Emerald Isle'
    },
    CHOWAN: {
      '1': 'East Edenton',
      '2': 'West Edenton',
      '3': 'Rocky Hock',
      '4': 'Center Hill',
      '5': 'Wardville',
      '6': 'Yeopim'
    },
    MADISON: {
      'EBBS C': 'Ebbs Chapel',
      'HOT SP': 'Hot Springs',
      'MARS H': 'Mars Hill'
    },
    CHEROKEE: {
      ANNW: 'Andrews North Ward',
      ANSW: 'Andrews South Ward',
      CSON: 'Culberson',
      GCRK: 'Grape Creek',
      HIWA: 'Hiwassee Dam',
      MARB: 'Marble',
      PCHT: 'Peachtree',
      RGER: 'Ranger',
      TOPT: 'Topton',
      UNKA: 'Unaka'
    },
    BRUNSWICK: {
      SB02: 'Boiling Spring Lakes',
      SB01: 'Bolivia',
      CB02: 'Shallotte',
      CB03: 'Frying Pan',
      WB06: 'Grissettown',
      NB02: 'Leland',
      WB03: 'Longwood',
      NB03: 'Town Creek',
      NB05: 'Woodburn',
      CB01: 'Supply',
      WB01: 'Waccamaw'
    },
    CASWELL: {
      PH: 'Prospect Hill',
      PROVI: 'Providence'
    },
    JACKSON: {
      SDC: 'Sylva South Ward'
    },
    CURRITUCK: {
      CO: 'Coinjock'
    },
    DARE: {
      FRCO: 'Frisco'
    },
    COLUMBUS: {
      P01A: 'Bogue',
      P06: 'Cerro Gordo',
      P07: 'Chadbourn',
      P14: 'Ransom',
      P15: 'Tatum',
      P16B: 'Waccamaw',
      P82: 'NW Whiteville'
    },
    DAVIE: {
      '01': 'North Calahaln',
      '02': 'South Calahaln',
      '03': 'Clarksville',
      '04': 'Cooleemee',
      '05': 'Farmington',
      '06': 'Fulton',
      '07': 'Jerusalem',
      '09': 'South Mocksville',
      '10': 'East Shady Grove',
      '11': 'West Shady Grove',
      '12': 'Smith Grove',
      '13': 'Hillsdale'
    },
    JONES: {
      P01: 'Beaver Creek',
      P02: 'Chinquapin',
      P03: 'Cypress Creek',
      P04: 'Pollocksville',
      P05: 'Trenton',
      P06: 'Tuckahoe',
      P07: 'White Oak'
    },
    HAYWOOD: {
      P: 'Pigeon'
    },
    MARTIN: {
      GSN: 'Goose Nest',
      GRF: 'Griffins',
      HMT: 'Hamilton',
      JMV: 'Jamesville'
    },
    MCDOWELL: {
      'WEST M': 'West Marion'
    },
    MOORE: {
      'EUR-WP': 'Eureka/Whispering Pines',
      PHC: 'Pinehurst C',
      SSP: 'South Southern Pines'
    },
    NASH: {
      P01A: 'Bailey',
      P05A: 'Coopers',
      P08A: 'Nashville',
      P09A: 'Castalia',
      P10A: 'Griffins',
      P11A: 'Red Oak',
      P15A: 'Oak Level'
    },
    NORTHAMPTON: {
      CREEKS: 'Creeksville',
      GALATI: 'Galatia',
      GAPL: 'Garysburg/Pleasant Hill',
      GASTON: 'Gaston',
      'LAKE G': 'Lake Gaston',
      LASKER: 'Lasker',
      NEWTOW: 'Newtown',
      'RICH S': 'Rich Square',
      SEABOA: 'Seaboard',
      SEVERN: 'Severn'
    },
    CLEVELAND: {
      'KM N': 'Kings Mountain North',
      'KM S': 'Kings Mountain South',
      'S C': 'Shelby Central',
      'S S': 'Shelby South'
    },
    ORANGE: {
      CA: 'Carr',
      CB1: 'Carrboro',
      OW1: 'Owasa',
      WW1: 'Westwood'
    },
    STANLY: {
      '0015': 'Badin',
      '0021': 'Endy',
      '0026': 'Tyson',
      '0120': 'Almond'
    },
    SURRY: {
      '12': 'Mt Airy 1',
      '15': 'Mt Airy 5',
      '16': 'Mt Airy 6',
      '17': 'Mt Airy 7',
      '19': 'Mt Airy 9'
    },
    WILSON: {
      PRBL: 'Black Creek',
      PRCR: 'Crossroads',
      PRGA: 'Gardners',
      PROL: 'Old Fields',
      PRSA: 'Saratoga',
      PRSP: 'Spring Hill',
      PRST: 'Stantonsburg',
      PRTA: 'Taylors',
      PRTO: 'Toisnot',
      PRWA: 'Wilson A',
      PRWB: 'Wilson B',
      PRWC: 'Wilson C',
      PRWD: 'Wilson D',
      PRWE: 'Wilson E',
      PRWH: 'Wilson H',
      PRWI: 'Wilson I',
      PRWJ: 'Wilson J',
      PRWK: 'Wilson K',
      PRWL: 'Wilson L',
      PRWM: 'Wilson M',
      PRWN: 'Wilson N',
      PRWP: 'Wilson P',
      PRWQ: 'Wilson Q',
      PRWR: 'Wilson R'
    },
    CATAWBA: {
      '28': 'St. Stephens',
      '29': 'St. Stephens'
    }
  };

  for (const [county, countyOverrides] of Object.entries(overrides)) {
    if (!counties[county]) counties[county] = {};
    for (const [code, displayName] of Object.entries(countyOverrides)) {
      counties[county][code] = displayName;
    }
  }

  return counties;
}

function normalizeAliasNameCandidate(raw) {
  const s = String(raw || '').trim().toUpperCase();
  if (!s) return '';
  const cleaned = s.replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!cleaned) return '';
  if (/VOTING\s*DISTRICT/i.test(cleaned)) return '';
  if (/^\d+$/.test(cleaned)) return '';
  return cleaned;
}

function collapseRedundantLeadingToken(raw) {
  const cleaned = normalizeAliasNameCandidate(raw);
  if (!cleaned) return '';
  const tokens = cleaned.split(/\s+/).filter(Boolean);
  if (tokens.length < 2) return cleaned;
  const [first, second, ...rest] = tokens;
  if (first.length >= 4 && second.startsWith(first.slice(0, 3))) {
    return [second, ...rest].join(' ').trim();
  }
  return cleaned;
}

function isCodeLikeToken(raw) {
  const s = String(raw || '').trim().toUpperCase();
  if (!s) return true;
  const compact = s.replace(/[^A-Z0-9]/g, '');
  if (!compact) return true;
  // Alias keys that include digits are almost always codes, not names (EH1, 0001, 00CRDM).
  if (/[0-9]/.test(compact)) return true;
  // Short all-letter tokens are usually precinct codes (CRDM, BCK), not display names.
  if (compact.length <= 4 && /^[A-Z]+$/.test(compact)) return true;
  return false;
}

function scoreNameCandidate(raw) {
  const s = normalizeAliasNameCandidate(raw);
  if (!s) return -1e9;
  const letters = (s.match(/[A-Z]/g) || []).length;
  const digits = (s.match(/[0-9]/g) || []).length;
  const spaces = (s.match(/\s/g) || []).length;
  let score = 0;
  score += letters * 2.2;
  score -= digits * 3.5;
  score += spaces * 1.0;
  score += Math.min(24, s.length);
  if (/VOTING\s*DISTRICT/i.test(s)) score -= 1000;
  if (/^(EARLY|ABSENTEE|PROVISIONAL|ONE\s+STOP|MAIL)/i.test(s)) score -= 20;
  return score;
}

function extractNameFromAlias(aliasRaw, codeRaw) {
  const alias = String(aliasRaw || '').trim().toUpperCase();
  const code = String(codeRaw || '').trim().toUpperCase();
  if (!alias || !code) return '';
  if (alias === code) return '';

  let rest = '';
  if (alias.startsWith(code)) {
    rest = alias.slice(code.length).trim();
    rest = rest.replace(/^[_\s]+/, '').trim();
  }
  if (!rest) return '';
  rest = rest.replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!rest) return '';
  if (/VOTING\s*DISTRICT/i.test(rest)) return '';

  const codeCompact = code.replace(/[^A-Z0-9]/g, '');
  const restCompact = rest.replace(/[^A-Z0-9]/g, '');
  if (restCompact === codeCompact) return '';
  if (restCompact.endsWith(codeCompact) && restCompact.length <= codeCompact.length + 2) return '';

  // Avoid returning another compact code token. Allow digits/spaces in real names (e.g. "LEXINGTON 1 22").
  if (!/\s/.test(rest)) {
    const compactOnly = rest.replace(/[^A-Z0-9]/g, '');
    if (compactOnly.length <= 6 && /^[A-Z0-9]+$/.test(compactOnly)) return '';
  }
  const cleaned = normalizeAliasNameCandidate(rest);
  if (!cleaned) return '';
  return cleaned;
}

function setBestNameForCode(perCounty, code, nameCandidate) {
  if (!perCounty || !code || !nameCandidate) return;
  const cand = collapseRedundantLeadingToken(nameCandidate);
  if (!cand) return;
  const prev = perCounty.get(code) || '';
  if (!prev) {
    perCounty.set(code, cand);
    return;
  }
  const prevScore = scoreNameCandidate(prev);
  const candScore = scoreNameCandidate(cand);
  if (candScore > prevScore + 1e-6) {
    perCounty.set(code, cand);
    return;
  }
  if (Math.abs(candScore - prevScore) < 1e-6 && cand.length > prev.length) {
    perCounty.set(code, cand);
  }
}

function buildFriendlyNamesIndex(aliasIndexPayload) {
  const counties = aliasIndexPayload?.counties || {};
  const out = {};

  for (const [countyRaw, aliasObj] of Object.entries(counties)) {
    if (!aliasObj || typeof aliasObj !== 'object') continue;
    const perCounty = new Map();

    for (const [aliasRaw, codesRaw] of Object.entries(aliasObj)) {
      const alias = String(aliasRaw || '').trim().toUpperCase();
      const codes = Array.isArray(codesRaw)
        ? Array.from(new Set(codesRaw.map(v => String(v || '').trim().toUpperCase()).filter(Boolean)))
        : [];
      if (!alias || !codes.length) continue;

      for (const code of codes) {
        const extracted = extractNameFromAlias(alias, code);
        if (extracted) {
          setBestNameForCode(perCounty, code, extracted);
          continue;
        }
        // Only treat an alias key as a "name-only" label when it *doesn't* start with the code token.
        // This avoids bad picks like "ANTI 00ANTI" becoming a "name" for code "ANTI".
        if (codes.length === 1 && !isCodeLikeToken(alias) && !alias.startsWith(String(code || '').trim().toUpperCase())) {
          setBestNameForCode(perCounty, code, alias);
        }
      }
    }

    if (!perCounty.size) continue;
    const outCounty = {};
    for (const [code, name] of perCounty.entries()) {
      outCounty[code] = formatDisplayName(name);
    }
    out[countyRaw] = outCounty;
  }

  return applyManualOverrides(out);
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const inputPath = process.argv[2]
    ? path.resolve(process.argv[2])
    : path.join(repoRoot, 'data', 'precinct_alias_index.json');
  const outputPath = process.argv[3]
    ? path.resolve(process.argv[3])
    : path.join(repoRoot, 'data', 'precinct_friendly_names.json');

  const payload = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  const counties = buildFriendlyNamesIndex(payload);
  const out = {
    version: 1,
    generated_at: new Date().toISOString(),
    generated_from: [path.relative(repoRoot, inputPath).replace(/\\/g, '/')],
    counties
  };

  fs.writeFileSync(outputPath, JSON.stringify(out), 'utf8');
  console.log(`Wrote ${Object.keys(counties).length} counties -> ${path.relative(repoRoot, outputPath)}`);
}

if (require.main === module) main();
