"""
Block/district-structure-assisted disambiguation for one election year.

Uses county-level district-profile frequencies from already matched keys to
resolve ambiguous keys conservatively.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from build_district_results_2024_lines import (
    _norm,
    build_precinct_alias_index,
    enrich_alias_index_from_vtd,
    load_precinct_overrides,
    resolve_precinct_key,
)


def _load_precinct_profiles(data_dir: Path) -> dict[str, tuple[str, str, str]]:
    def top_district(path: Path) -> dict[str, str]:
        rows: dict[str, tuple[str, float]] = {}
        with open(path, "r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                k = _norm(r["precinct_key"])
                d = _norm(r["district"])
                w = float(r["area_weight"])
                if (k not in rows) or (w > rows[k][1]):
                    rows[k] = (d, w)
        return {k: d for k, (d, _) in rows.items()}

    h = top_district(data_dir / "crosswalks" / "precinct_to_2024_state_house.csv")
    s = top_district(data_dir / "crosswalks" / "precinct_to_2024_state_senate.csv")
    c = top_district(data_dir / "crosswalks" / "precinct_to_cd118.csv")

    keys = set(h) | set(s) | set(c)
    out: dict[str, tuple[str, str, str]] = {}
    for k in keys:
        out[k] = (h.get(k, ""), s.get(k, ""), c.get(k, ""))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", required=True)
    ap.add_argument("--min-support", type=int, default=3)
    ap.add_argument("--min-gap", type=int, default=2)
    ap.add_argument(
        "--out-csv",
        type=Path,
        default=None,
        help="Output override suggestions CSV.",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    src = json.load(open(data_dir / "nc_elections_aggregated.json", "r", encoding="utf-8"))
    year_data = src.get("results_by_year", {}).get(str(args.year), {})

    # Build alias index consistent with pipeline.
    voting_geojson = data_dir / "Voting_Precincts.geojson"
    alias_index = build_precinct_alias_index(voting_geojson)
    enrich_alias_index_from_vtd(alias_index, vtd_path=data_dir / "census" / "tl_2008_37_vtd00_merged.geojson", county_col="COUNTYFP00", code_col="VTDST00", name_col="NAME00")
    enrich_alias_index_from_vtd(alias_index, vtd_path=data_dir / "census" / "tl_2012_37_vtd10" / "tl_2012_37_vtd10.shp", county_col="COUNTYFP10", code_col="VTDST10", name_col="NAME10")
    v20 = next(
        (
            p
            for p in [
                data_dir / "census" / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.geojson",
                data_dir / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.geojson",
                data_dir / "census" / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp",
                data_dir / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp",
            ]
            if p.exists()
        ),
        data_dir / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp",
    )
    enrich_alias_index_from_vtd(alias_index, vtd_path=v20, county_col="COUNTYFP20", code_col="VTDST20", name_col="NAME20")

    overrides = load_precinct_overrides(data_dir / "mappings" / "precinct_key_overrides.csv")
    year_overrides = overrides.get(str(args.year), {})
    star_overrides = overrides.get("*", {})

    profiles = _load_precinct_profiles(data_dir)

    county_profile_counts: dict[str, Counter] = defaultdict(Counter)
    ambiguous_keys: set[str] = set()

    for _, office_data in year_data.items():
        results = office_data.get("general", {}).get("results", {})
        for raw_key in results.keys():
            k = _norm(raw_key)
            k = year_overrides.get(k, star_overrides.get(k, k))
            resolved, status = resolve_precinct_key(k, alias_index)
            if status == "ambiguous":
                ambiguous_keys.add(k)
                continue
            if not resolved:
                continue
            county = resolved.split(" - ", 1)[0] if " - " in resolved else ""
            prof = profiles.get(resolved)
            if county and prof:
                county_profile_counts[county][prof] += 1

    suggestions_path = data_dir / "reports" / "precinct_key_overrides_2020_suggestions.csv"
    sugg_by_raw: dict[str, list[str]] = defaultdict(list)
    if suggestions_path.exists():
        with open(suggestions_path, "r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if _norm(r.get("year", "")) != _norm(args.year):
                    continue
                raw = _norm(r.get("raw_precinct_key", ""))
                if not raw:
                    continue
                for k in [
                    _norm(r.get("suggested_canonical_precinct_key", "")),
                    _norm(r.get("candidate_2", "")),
                    _norm(r.get("candidate_3", "")),
                ]:
                    if k and k not in sugg_by_raw[raw]:
                        sugg_by_raw[raw].append(k)

    rows: list[dict] = []
    for raw in sorted(ambiguous_keys):
        county = raw.split(" - ", 1)[0] if " - " in raw else ""
        cands = sugg_by_raw.get(raw, [])
        # Include deterministic underscore prefix candidate.
        if "_" in raw:
            pref = _norm(raw.split("_", 1)[0])
            if pref and pref not in cands:
                cands.insert(0, pref)
        cands = [c for c in cands if c in profiles and c.startswith(f"{county} - ")]
        if len(cands) < 2:
            continue
        score_rows = []
        for c in cands:
            prof = profiles.get(c)
            support = county_profile_counts[county][prof] if prof else 0
            score_rows.append((c, support, prof))
        score_rows.sort(key=lambda x: x[1], reverse=True)
        top_c, top_s, top_p = score_rows[0]
        snd_s = score_rows[1][1] if len(score_rows) > 1 else 0
        if top_s < args.min_support:
            continue
        if (top_s - snd_s) < args.min_gap:
            continue
        rows.append(
            {
                "year": str(args.year),
                "raw_precinct_key": raw,
                "canonical_precinct_key": top_c,
                "county": county,
                "top_profile": "|".join(top_p) if top_p else "",
                "top_support": top_s,
                "second_support": snd_s,
                "candidate_count": len(cands),
                "method": "block_profile_county_support",
            }
        )

    out_csv = args.out_csv if args.out_csv else (data_dir / "reports" / f"block_assisted_overrides_{args.year}.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "year",
                "raw_precinct_key",
                "canonical_precinct_key",
                "county",
                "top_profile",
                "top_support",
                "second_support",
                "candidate_count",
                "method",
            ],
        )
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {out_csv} rows={len(rows)}")


if __name__ == "__main__":
    main()
