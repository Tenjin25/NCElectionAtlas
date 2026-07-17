(function initializeAtlasModeling(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AtlasModeling = Object.freeze(api);
}(typeof globalThis !== 'undefined' ? globalThis : this, function createAtlasModeling() {
  function stableStringify(value) {
    const seen = new WeakSet();
    const recur = (item) => {
      if (item === null || item === undefined) return item;
      const type = typeof item;
      if (type === 'number') return Number.isFinite(item) ? item : String(item);
      if (type === 'string' || type === 'boolean') return item;
      if (type !== 'object') return String(item);
      if (seen.has(item)) return '[Circular]';
      seen.add(item);
      if (Array.isArray(item)) return item.map(recur);
      const output = {};
      Object.keys(item).sort().forEach(key => { output[key] = recur(item[key]); });
      return output;
    };
    try {
      return JSON.stringify(recur(value));
    } catch (_) {
      return String(value);
    }
  }

  function getDefinitionSignature(modeledDefinition) {
    if (!modeledDefinition) return '';
    const contestType = String(modeledDefinition?.contestType || '').trim();
    const year = Number(modeledDefinition?.year);
    if (!contestType || !Number.isFinite(year)) return '';
    return `${contestType}_${year}|${stableStringify(modeledDefinition)}`;
  }

  function getCountyBehaviorLabel(mode) {
    const key = String(mode || 'balanced').trim().toLowerCase();
    const labels = {
      balanced: 'Balanced counties',
      suburban_rebound: 'Suburban rebound',
      rural_surge: 'Rural surge',
      incumbent_friendly: 'Incumbent-friendly',
      volatile: 'Volatile / low-confidence'
    };
    return labels[key] || labels.balanced;
  }

  function inferConfidence(modeled, baseModeled = null) {
    if (!modeled) return { label: 'Low', range: '\u00b12.0 pts' };
    const blend = Number(modeled?.blendWeight);
    const bonus = Number(modeled?.candidateBonusScale);
    const turnout = Number(modeled?.turnoutFactor);
    const behavior = String(modeled?.countyBehaviorMode || 'balanced').trim().toLowerCase();
    const uncertaintyBoost = Number(modeled?.uncertaintyBoost);
    const blendDelta = (baseModeled && Number.isFinite(blend) && Number.isFinite(Number(baseModeled?.blendWeight)))
      ? Math.abs(blend - Number(baseModeled.blendWeight))
      : 0;
    const turnoutDelta = (baseModeled && Number.isFinite(turnout) && Number.isFinite(Number(baseModeled?.turnoutFactor)))
      ? Math.abs(turnout - Number(baseModeled.turnoutFactor))
      : 0;
    const bonusDelta = (baseModeled && Number.isFinite(bonus) && Number.isFinite(Number(baseModeled?.candidateBonusScale)))
      ? Math.abs(bonus - Number(baseModeled.candidateBonusScale))
      : 0;

    let score = 0;
    score += Math.max(0, 0.30 - (blendDelta * 0.65));
    score += Math.max(0, 0.30 - (turnoutDelta * 0.80));
    score += Math.max(0, 0.22 - (bonusDelta * 0.22));
    if (behavior === 'balanced' || behavior === 'incumbent_friendly') score += 0.14;
    if (behavior === 'suburban_rebound' || behavior === 'rural_surge') score += 0.05;
    if (behavior === 'volatile') score -= 0.22;
    if (Number.isFinite(uncertaintyBoost) && uncertaintyBoost > 1) {
      score -= Math.min(0.18, (uncertaintyBoost - 1) * 0.28);
    }

    let label = 'Medium';
    if (score >= 0.60) label = 'High';
    else if (score < 0.36) label = 'Low';
    const range = label === 'High' ? '\u00b11.4 pts' : (label === 'Medium' ? '\u00b12.0 pts' : '\u00b13.0 pts');
    return { label, range };
  }

  return {
    stableStringify,
    getDefinitionSignature,
    getCountyBehaviorLabel,
    inferConfidence
  };
}));
