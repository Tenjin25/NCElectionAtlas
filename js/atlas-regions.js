(function initializeAtlasRegions(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AtlasRegions = Object.freeze(api);
}(typeof globalThis !== 'undefined' ? globalThis : this, function createAtlasRegions() {
  function normalizeCountyName(name) {
    return (name || '')
      .toString()
      .replace(/\s+COUNTY$/i, '')
      .replace(/[^a-z0-9 .\-]/gi, '')
      .replace(/\s+/g, ' ')
      .trim()
      .toUpperCase();
  }

  function getCountySet(counties) {
    return new Set(
      (Array.isArray(counties) ? counties : [])
        .map(normalizeCountyName)
        .filter(Boolean)
    );
  }

  function aggregateContestRows(rows, contestType, counties) {
    const countySet = getCountySet(counties);
    const type = String(contestType || '').trim();
    let dem = 0;
    let rep = 0;
    let other = 0;
    let total = 0;
    let demCandidate = '';
    let repCandidate = '';
    const matchedCounties = new Set();
    const countySums = new Map();

    (Array.isArray(rows) ? rows : []).forEach(row => {
      const countyRaw = ((row?.county || '').toString().split(' - ')[0] || '').trim();
      const countyNorm = normalizeCountyName(countyRaw);
      if (!countyNorm || !countySet.has(countyNorm)) return;

      matchedCounties.add(countyNorm);
      const node = countySums.get(countyNorm) || { dem: 0, rep: 0, other: 0, total: 0 };
      node.dem += Number(row?.[`${type}_dem`] || 0);
      node.rep += Number(row?.[`${type}_rep`] || 0);
      node.other += Number(row?.[`${type}_other`] || 0);
      node.total += Number(row?.[`${type}_total`] || 0);
      countySums.set(countyNorm, node);
      if (!demCandidate) {
        demCandidate = (row?.[`${type}_dem_candidate`] || '').toString().trim();
      }
      if (!repCandidate) {
        repCandidate = (row?.[`${type}_rep_candidate`] || '').toString().trim();
      }
    });

    const official = rows?.__officialCountyTotals || {};
    countySet.forEach(county => {
      const source = official[county];
      const summed = countySums.get(county);
      const node = source ? {
        dem: Number(source.dem_votes || 0),
        rep: Number(source.rep_votes || 0),
        other: Number(source.other_votes || 0),
        total: Number(source.total_votes || 0)
      } : summed;
      if (!node) return;
      matchedCounties.add(county);
      dem += node.dem;
      rep += node.rep;
      other += node.other;
      total += node.total;
      if (source && !demCandidate) demCandidate = String(source.dem_candidate || '');
      if (source && !repCandidate) repCandidate = String(source.rep_candidate || '');
    });

    return {
      dem,
      rep,
      other,
      total,
      demCandidate,
      repCandidate,
      matchedCounties: matchedCounties.size,
      totalCounties: countySet.size
    };
  }

  return {
    normalizeCountyName,
    getCountySet,
    aggregateContestRows
  };
}));
