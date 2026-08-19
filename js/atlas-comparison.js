(function initializeAtlasComparison(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AtlasComparison = Object.freeze(api);
}(typeof globalThis !== 'undefined' ? globalThis : this, function createAtlasComparison() {
  function parseContestValue(value) {
    const raw = String(value || '').trim();
    const idx = raw.lastIndexOf('_');
    if (idx <= 0) return { value: raw, contestType: '', year: NaN };
    const year = Number(raw.slice(idx + 1));
    return {
      value: raw,
      contestType: raw.slice(0, idx),
      year: Number.isFinite(year) ? year : NaN
    };
  }

  function signedMarginPct(demVotes, repVotes, totalVotes) {
    const dem = Number(demVotes || 0);
    const rep = Number(repVotes || 0);
    const suppliedTotal = Number(totalVotes);
    const total = Number.isFinite(suppliedTotal) && suppliedTotal > 0
      ? suppliedTotal
      : dem + rep;
    return total > 0 ? ((rep - dem) / total) * 100 : NaN;
  }

  function compareSignedMargins(primarySigned, comparisonSigned) {
    const primary = Number(primarySigned);
    const comparison = Number(comparisonSigned);
    if (!Number.isFinite(primary) || !Number.isFinite(comparison)) {
      return { primary, comparison, delta: NaN, direction: 'none', magnitude: NaN };
    }
    const delta = primary - comparison;
    return {
      primary,
      comparison,
      delta,
      direction: Math.abs(delta) < 0.005 ? 'even' : (delta > 0 ? 'rep' : 'dem'),
      magnitude: Math.abs(delta)
    };
  }

  function pickDefaultComparisonContest(primaryValue, optionValues) {
    const primary = parseContestValue(primaryValue);
    const values = Array.from(new Set((optionValues || []).map(v => String(v || '').trim()).filter(Boolean)))
      .filter(value => value !== primary.value);
    if (!values.length) return '';

    const parsed = values.map(parseContestValue);
    if (primary.contestType && Number.isFinite(primary.year)) {
      const sameType = parsed
        .filter(item => item.contestType === primary.contestType && Number.isFinite(item.year))
        .sort((a, b) => {
          const aPrior = a.year < primary.year ? 0 : 1;
          const bPrior = b.year < primary.year ? 0 : 1;
          if (aPrior !== bPrior) return aPrior - bPrior;
          const aDistance = Math.abs(primary.year - a.year);
          const bDistance = Math.abs(primary.year - b.year);
          if (aDistance !== bDistance) return aDistance - bDistance;
          return b.year - a.year;
        });
      if (sameType.length) return sameType[0].value;

      const sameYear = parsed.find(item => item.year === primary.year);
      if (sameYear) return sameYear.value;
    }
    return values[0];
  }

  return {
    parseContestValue,
    signedMarginPct,
    compareSignedMargins,
    pickDefaultComparisonContest
  };
}));
