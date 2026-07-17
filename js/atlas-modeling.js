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

  function computeStatewideMarginFromDistrictResults(results, signedMargin) {
    const totals = Object.values(results || {}).reduce((accumulator, row) => {
      accumulator.dem += Number(row?.dem_votes || 0);
      accumulator.rep += Number(row?.rep_votes || 0);
      accumulator.total += Number(row?.total_votes || 0);
      return accumulator;
    }, { dem: 0, rep: 0, total: 0 });
    return signedMargin(totals.dem, totals.rep, totals.total);
  }

  function buildContestRow(baseRow, modeledDefinition, climateSwingPct, options = {}, dependencies = {}) {
    const baseContestType = modeledDefinition.baseContestType;
    const contestType = modeledDefinition.contestType;
    const shifted = dependencies.shiftVotes(
      Number(baseRow?.[`${baseContestType}_dem`] || 0),
      Number(baseRow?.[`${baseContestType}_rep`] || 0),
      Number(baseRow?.[`${baseContestType}_other`] || 0),
      Number(baseRow?.[`${baseContestType}_total`] || 0),
      climateSwingPct
    );
    const targetTotal = options && Number.isFinite(Number(options.targetTotal))
      ? Number(options.targetTotal)
      : null;
    const scaled = targetTotal ? dependencies.rescaleVotes(shifted, targetTotal) : shifted;
    const signed = dependencies.signedMargin(scaled.dem, scaled.rep, scaled.total);
    const winner = signed > 0 ? 'REP' : (signed < 0 ? 'DEM' : 'TIE');
    const winnerKey = winner === 'REP' ? 'R' : (winner === 'DEM' ? 'D' : 'T');
    const color = winnerKey === 'T'
      ? '#9ca3af'
      : dependencies.colorForMargin(Math.abs(signed), winnerKey);
    const row = {
      year: Number(modeledDefinition.year),
      county: baseRow?.county || '',
      [`${contestType}_dem`]: scaled.dem,
      [`${contestType}_rep`]: scaled.rep,
      [`${contestType}_other`]: scaled.other,
      [`${contestType}_total`]: scaled.total,
      [`${contestType}_dem_candidate`]: modeledDefinition.demCandidate || '',
      [`${contestType}_rep_candidate`]: modeledDefinition.repCandidate || '',
      [`${contestType}_margin`]: Math.round(scaled.rep - scaled.dem),
      [`${contestType}_margin_pct`]: signed,
      [`${contestType}_winner`]: winner,
      [`${contestType}_color`]: color
    };
    const modelMeta = options?.modelMeta || null;
    if (modelMeta && Number.isFinite(Number(modelMeta.baselineNoCandidateSigned))) {
      row.__model_baseline_margin_pct = Number(modelMeta.baselineNoCandidateSigned);
      row.__model_with_candidates_margin_pct = Number.isFinite(Number(modelMeta.desiredSigned))
        ? Number(modelMeta.desiredSigned)
        : Number(signed);
      row.__model_candidate_effect_d_pts = Number.isFinite(Number(modelMeta.candidateEffectDemPts))
        ? Number(modelMeta.candidateEffectDemPts)
        : 0;
      row.__model_candidate_effect_durable_pts = Number.isFinite(Number(modelMeta.candidateEffectDurableDemPts))
        ? Number(modelMeta.candidateEffectDurableDemPts)
        : 0;
      row.__model_candidate_effect_personal_pts = Number.isFinite(Number(modelMeta.candidateEffectPersonalDemPts))
        ? Number(modelMeta.candidateEffectPersonalDemPts)
        : 0;
      row.__model_candidate_effect_local_d_pts = Number.isFinite(Number(modelMeta.candidateEffectLocalDemPts))
        ? Number(modelMeta.candidateEffectLocalDemPts)
        : 0;
      row.__model_candidate_effect_county_type_d_pts = Number.isFinite(Number(modelMeta.candidateEffectCountyTypeDemPts))
        ? Number(modelMeta.candidateEffectCountyTypeDemPts)
        : 0;
      row.__model_anchor_spread_pts = Number.isFinite(Number(modelMeta.anchorSpreadPts))
        ? Number(modelMeta.anchorSpreadPts)
        : NaN;
      row.__model_input_disagreement = String(modelMeta.inputDisagreement || '');
      row.__model_anchors_aligned = Number(modelMeta.anchorsAligned || 0);
      row.__model_confidence_label = String(modelMeta.modelConfidenceLabel || '');
      row.__model_confidence_band = String(modelMeta.modelConfidenceBand || '');
      row.__model_influence_presidential_climate_pts = Number.isFinite(Number(modelMeta.influencePresidentialClimatePts))
        ? Number(modelMeta.influencePresidentialClimatePts)
        : NaN;
      row.__model_influence_senate_baseline_pts = Number.isFinite(Number(modelMeta.influenceSenateBaselinePts))
        ? Number(modelMeta.influenceSenateBaselinePts)
        : NaN;
      row.__model_influence_extra_movement_pts = Number.isFinite(Number(modelMeta.influenceExtraModeledMovementPts))
        ? Number(modelMeta.influenceExtraModeledMovementPts)
        : NaN;
      row.__model_influence_crossover_dem_pts = Number.isFinite(Number(modelMeta.influenceCrossoverDemPts))
        ? Number(modelMeta.influenceCrossoverDemPts)
        : NaN;
      row.__model_explain_tags = Array.isArray(modelMeta.explanationTags)
        ? modelMeta.explanationTags.map(value => String(value || '').trim()).filter(Boolean).join(' \u2022 ')
        : '';
    }
    return row;
  }

  function buildDistrictResultRow(baseRow, modeledDefinition, climateSwingPct, targetTotalOverride, dependencies = {}) {
    const shifted = dependencies.shiftVotes(
      Number(baseRow?.dem_votes || 0),
      Number(baseRow?.rep_votes || 0),
      Number(baseRow?.other_votes || 0),
      Number(baseRow?.total_votes || 0),
      climateSwingPct
    );
    const desired = Number(targetTotalOverride);
    const scaled = Number.isFinite(desired) && desired > 0
      ? dependencies.rescaleVotes(shifted, desired)
      : shifted;
    const signed = dependencies.signedMargin(scaled.dem, scaled.rep, scaled.total);
    const winner = signed > 0 ? 'REP' : (signed < 0 ? 'DEM' : 'TIE');
    const winnerKey = winner === 'REP' ? 'R' : (winner === 'DEM' ? 'D' : 'T');
    const color = winnerKey === 'T'
      ? '#9ca3af'
      : dependencies.colorForMargin(Math.abs(signed), winnerKey);
    return {
      ...baseRow,
      dem_votes: scaled.dem,
      rep_votes: scaled.rep,
      other_votes: scaled.other,
      total_votes: scaled.total,
      dem_candidate: modeledDefinition.demCandidate || '',
      rep_candidate: modeledDefinition.repCandidate || '',
      margin: Math.round(scaled.rep - scaled.dem),
      margin_pct: signed,
      winner,
      competitiveness: {
        ...(baseRow?.competitiveness || {}),
        color
      }
    };
  }

  return {
    stableStringify,
    getDefinitionSignature,
    getCountyBehaviorLabel,
    inferConfidence,
    computeStatewideMarginFromDistrictResults,
    buildContestRow,
    buildDistrictResultRow
  };
}));
