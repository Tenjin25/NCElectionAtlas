"""
Generate 2020 precinct override suggestions from unmatched/ambiguous diagnostics.

This creates a ranked review file that can be copied into:
  data/mappings/precinct_key_overrides.csv
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
from pathlib import Path

from build_district_results_2024_lines import (
    _compact,
    _extract_code_name_aliases,
    _norm,
    build_precinct_alias_index,
    enrich_alias_index_from_vtd,
)


def _load_county_rule_pack(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, dict] = {}
    for county, cfg in raw.items():
        out[_norm(county)] = cfg if isinstance(cfg, dict) else {}
    return out


def _load_geo_canonical_meta(voting_geojson: Path) -> dict[str, dict[str, str]]:
    geo = json.load(open(voting_geojson, "r", encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for f in geo.get("features", []):
        props = f.get("properties", {})
        county = _norm(props.get("county_nam", ""))
        prec_id = _norm(props.get("prec_id", ""))
        if not county or not prec_id:
            continue
        canonical = f"{county} - {prec_id}"
        out[canonical] = {
            "county": county,
            "prec_id": prec_id,
            "enr_desc": _norm(props.get("enr_desc", "")),
        }
    return out


def _score_candidate(raw_precinct: str, candidate_prec_id: str, candidate_desc: str) -> tuple[float, str]:
    raw = _norm(raw_precinct)
    code = _norm(candidate_prec_id)
    desc = _norm(candidate_desc)
    raw_c = _compact(raw)
    code_c = _compact(code)
    desc_c = _compact(desc)

    if raw == code:
        return 1.00, "exact_prec_id"
    if raw_c == code_c:
        return 0.98, "compact_prec_id"
    if desc and raw == desc:
        return 0.97, "exact_enr_desc"
    if desc and raw_c == desc_c:
        return 0.95, "compact_enr_desc"

    joined = f"{code} {desc}".strip()
    joined_c = _compact(joined)
    if joined and raw in joined:
        return 0.93, "raw_in_code_desc"
    if joined_c and raw_c and raw_c in joined_c:
        return 0.91, "compact_raw_in_code_desc"

    code_ratio = difflib.SequenceMatcher(a=raw_c, b=code_c).ratio() if raw_c and code_c else 0.0
    desc_ratio = difflib.SequenceMatcher(a=raw_c, b=desc_c).ratio() if raw_c and desc_c else 0.0
    best = max(code_ratio, desc_ratio)
    return best * 0.9, "fuzzy"


def _best_candidates(
    raw_key: str,
    alias_index: dict[str, dict[str, set[str]]],
    canonical_meta: dict[str, dict[str, str]],
    topn: int = 3,
) -> list[tuple[str, float, str]]:
    if " - " not in raw_key:
        return []
    county, precinct = raw_key.split(" - ", 1)
    county = _norm(county)
    precinct = _norm(precinct)
    county_aliases = alias_index.get(county, {})

    candidates: set[str] = set()
    for a in _extract_code_name_aliases(precinct):
        candidates.update(county_aliases.get(a, set()))
    if not candidates:
        return []

    scored: list[tuple[str, float, str]] = []
    for canonical in candidates:
        meta = canonical_meta.get(canonical, {})
        score, reason = _score_candidate(
            raw_precinct=precinct,
            candidate_prec_id=meta.get("prec_id", canonical.split(" - ", 1)[-1]),
            candidate_desc=meta.get("enr_desc", ""),
        )
        scored.append((canonical, score, reason))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:topn]


def _classify_tier(
    *,
    county: str,
    top_score: float,
    reason: str,
    second_score: float,
    county_rule_pack: dict[str, dict],
) -> str:
    cfg = county_rule_pack.get(_norm(county), {})
    blocked_reasons = {_norm(r) for r in cfg.get("blocked_reasons", [])}
    review_reasons = {_norm(r) for r in cfg.get("review_reasons", [])}
    auto_reasons = {_norm(r) for r in cfg.get("auto_accept_reasons", [])}
    auto_min = float(cfg.get("auto_accept_min_score", 0.97))
    min_gap = float(cfg.get("min_second_gap", 0.03))

    r = _norm(reason)
    if r in blocked_reasons:
        return "MANUAL_REQUIRED"
    if r in review_reasons:
        return "AUTO_REVIEW"
    if r in auto_reasons and top_score >= auto_min and (top_score - second_score) >= min_gap:
        return "AUTO_ACCEPT"
    if top_score >= 0.97 and r in {"EXACT_PREC_ID", "COMPACT_PREC_ID", "EXACT_ENR_DESC"} and (top_score - second_score) >= 0.03:
        return "AUTO_ACCEPT"
    if top_score >= 0.90:
        return "AUTO_REVIEW"
    return "MANUAL_REQUIRED"


def main() -> None:
    ap = argparse.ArgumentParser(description="Suggest 2020 precinct key overrides from unmatched diagnostics.")
    ap.add_argument("--year", type=str, default="2020")
    ap.add_argument("--status", type=str, default="ambiguous,unmatched")
    ap.add_argument(
        "--in-examples",
        type=Path,
        default=Path("data/reports/unmatched_precinct_examples.csv"),
    )
    ap.add_argument(
        "--out-suggestions",
        type=Path,
        default=Path("data/reports/precinct_key_overrides_2020_suggestions.csv"),
    )
    ap.add_argument(
        "--ensure-overrides-csv",
        type=Path,
        default=Path("data/mappings/precinct_key_overrides.csv"),
    )
    ap.add_argument(
        "--county-rule-pack",
        type=Path,
        default=Path("data/mappings/precinct_county_rule_pack.json"),
        help="County-specific tiering policy JSON.",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    voting_geojson = data_dir / "2025Voting_Precincts.geojson"
    vtd_2008 = data_dir / "census" / "tl_2008_37_vtd00_merged.geojson"
    vtd_2012 = data_dir / "census" / "tl_2012_37_vtd10" / "tl_2012_37_vtd10.shp"
    vtd_2020_candidates = [
        data_dir / "census" / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.geojson",
        data_dir / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.geojson",
        data_dir / "census" / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp",
        data_dir / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp",
    ]
    vtd_2020 = next((p for p in vtd_2020_candidates if p.exists()), vtd_2020_candidates[0])

    statuses = {_norm(s) for s in args.status.split(",") if s.strip()}

    alias_index = build_precinct_alias_index(voting_geojson)
    enrich_alias_index_from_vtd(alias_index, vtd_path=vtd_2008, county_col="COUNTYFP00", code_col="VTDST00", name_col="NAME00")
    enrich_alias_index_from_vtd(alias_index, vtd_path=vtd_2012, county_col="COUNTYFP10", code_col="VTDST10", name_col="NAME10")
    enrich_alias_index_from_vtd(alias_index, vtd_path=vtd_2020, county_col="COUNTYFP20", code_col="VTDST20", name_col="NAME20")
    canonical_meta = _load_geo_canonical_meta(voting_geojson)
    county_rule_pack = _load_county_rule_pack(
        args.county_rule_pack if args.county_rule_pack.is_absolute() else root / args.county_rule_pack
    )

    in_examples = args.in_examples if args.in_examples.is_absolute() else root / args.in_examples
    out_suggestions = args.out_suggestions if args.out_suggestions.is_absolute() else root / args.out_suggestions
    overrides_csv = args.ensure_overrides_csv if args.ensure_overrides_csv.is_absolute() else root / args.ensure_overrides_csv

    rows = []
    with open(in_examples, "r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            if _norm(r.get("year", "")) != _norm(args.year):
                continue
            if _norm(r.get("status", "")) not in statuses:
                continue
            raw_key = _norm(r.get("precinct_key", ""))
            if not raw_key:
                continue

            best = _best_candidates(raw_key, alias_index, canonical_meta, topn=3)
            top = best[0] if best else ("", 0.0, "none")
            second_score = best[1][1] if len(best) > 1 else 0.0
            county = raw_key.split(" - ", 1)[0] if " - " in raw_key else ""
            tier = _classify_tier(
                county=county,
                top_score=top[1],
                reason=top[2],
                second_score=second_score,
                county_rule_pack=county_rule_pack,
            )
            rows.append(
                {
                    "year": args.year,
                    "status": _norm(r.get("status", "")),
                    "raw_precinct_key": raw_key,
                    "count": r.get("count", ""),
                    "suggested_canonical_precinct_key": top[0],
                    "score": f"{top[1]:.4f}",
                    "tier": tier,
                    "reason": top[2],
                    "candidate_2": best[1][0] if len(best) > 1 else "",
                    "candidate_3": best[2][0] if len(best) > 2 else "",
                }
            )

    out_suggestions.parent.mkdir(parents=True, exist_ok=True)
    tier_order = {"AUTO_ACCEPT": 0, "AUTO_REVIEW": 1, "MANUAL_REQUIRED": 2}
    rows.sort(key=lambda x: (tier_order.get(x["tier"], 9), -float(x["score"]), x["raw_precinct_key"]))
    with open(out_suggestions, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "year",
                "status",
                "raw_precinct_key",
                "count",
                "suggested_canonical_precinct_key",
                "score",
                "tier",
                "reason",
                "candidate_2",
                "candidate_3",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    if not overrides_csv.exists():
        overrides_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(overrides_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["year", "raw_precinct_key", "canonical_precinct_key"])

    print(f"Wrote suggestions: {out_suggestions}")
    print(f"Ensured overrides CSV exists: {overrides_csv}")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()
