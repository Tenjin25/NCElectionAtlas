(function initializeAtlasCore(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AtlasCore = Object.freeze(api);
}(typeof globalThis !== 'undefined' ? globalThis : this, function createAtlasCore() {
  const PRECINCT_ALIAS_COMMON_WORDS = Object.freeze([
    'PRECINCT',
    'PCT',
    'WARD',
    'DISTRICT',
    'TOWNSHIP',
    'BOX',
    'VOTING',
    'LOCATION'
  ]);

  function normalizeCountyToken(name) {
    return (name || '')
      .toString()
      .replace(/[^a-z0-9 .\-]/gi, '')
      .replace(/\s+/g, ' ')
      .trim()
      .toUpperCase();
  }

  function normalizePrecinctAliasToken(value) {
    let token = (value || '').toString().trim().toUpperCase();
    if (!token) return '';
    PRECINCT_ALIAS_COMMON_WORDS.forEach(word => {
      token = token.replace(new RegExp(word, 'g'), ' ');
    });
    token = token.replace(/[-_.]/g, ' ');
    token = token.replace(/\s+/g, ' ').trim();
    return token;
  }

  function compactPrecinctAliasToken(value) {
    return (value || '').toString().trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
  }

  function normalizeRowKey(value) {
    return (value || '').toString().trim().toUpperCase().replace(/\s+/g, ' ');
  }

  function signedMarginPctFromVotes(demVotes, repVotes, totalVotes) {
    const total = Number(totalVotes) || 0;
    if (total <= 0) return 0;
    return ((Number(repVotes) - Number(demVotes)) / total) * 100;
  }

  function rescaleVoteSetToTargetTotal(voteSet, targetTotal) {
    const desired = Math.max(0, Math.round(Number(targetTotal) || 0));
    const baseTotal = Math.max(0, Math.round(Number(voteSet?.total) || 0));
    if (!Number.isFinite(desired) || desired <= 0 || baseTotal <= 0) return voteSet;

    const scale = desired / baseTotal;
    let dem = Math.max(0, Math.round((Number(voteSet?.dem) || 0) * scale));
    let rep = Math.max(0, Math.round((Number(voteSet?.rep) || 0) * scale));
    const twoParty = dem + rep;
    if (twoParty > desired && twoParty > 0) {
      const demShare = dem / twoParty;
      dem = Math.max(0, Math.round(demShare * desired));
      rep = Math.max(0, desired - dem);
      return { dem, rep, other: 0, total: desired };
    }
    const other = Math.max(0, desired - twoParty);
    return { dem, rep, other, total: desired };
  }

  return {
    PRECINCT_ALIAS_COMMON_WORDS,
    normalizeCountyToken,
    normalizePrecinctAliasToken,
    compactPrecinctAliasToken,
    normalizeRowKey,
    signedMarginPctFromVotes,
    rescaleVoteSetToTargetTotal
  };
}));
