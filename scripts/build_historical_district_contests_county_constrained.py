#!/usr/bin/env python3
"""Experimental county-constrained historical legislative district builder.

This wrapper deliberately leaves the established historical builder unchanged.
It borrows that builder's parsing, aliases, precinct lineage, SF1/VAP weights,
and output code, replacing only its final district integerization in memory.
Every county/contest/party bucket is rounded across districts with the largest-
remainder method before county contributions are summed into districts.

The command line is identical to build_district_contests_from_batch_shatter.py.
Point --district-contests-dir at a staging directory until the audit is accepted.
"""

from __future__ import annotations

import sys
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

import build_district_contests_from_batch_shatter as legacy
from shatter_precinct_votes_vap import shatter_votes


PARTY_COLUMNS = ("dem_votes", "rep_votes", "other_votes")
_canonical_cache: dict[tuple[int, int, int, int], dict[str, dict[str, int]] | None] = {}
_component_audit: dict[str, dict[str, object]] = {}


def component_plan_key(scope: str, target_year: int) -> str | None:
    scope = str(scope).strip().lower()
    if scope not in {"state_house", "state_senate"} or target_year not in {2022, 2024}:
        return None
    return f"{target_year}_{scope}"


def exact_county_destinations(plan_key: str | None) -> dict[str, str]:
    if not plan_key:
        return {}
    path = Path("data/mappings/mixed_county_components.json")
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    exact = ((payload.get("plans") or {}).get(plan_key) or {}).get("exact_components") or {}
    destinations: dict[str, str] = {}
    for district, counties in exact.items():
        for county in counties or []:
            county = str(county).strip().upper()
            prior = destinations.get(county)
            if prior and prior != str(district):
                raise ValueError(f"Whole county {county} maps to both {prior} and {district}")
            destinations[county] = str(district).strip().lstrip("0") or "0"
    return destinations


def isolate_exact_county_components(
    allocations: pd.DataFrame,
    targets: dict[str, float],
    destinations: dict[str, str],
) -> pd.DataFrame:
    """Replace estimated rows for whole counties with one canonical exact row.

    Split counties retain their precinct/SF1 allocation. This makes the district
    result explicitly equal to exact whole-county votes plus estimated split-
    county votes, instead of allowing the two components to share fallback math.
    """
    if not destinations:
        return allocations
    exact_counties = set(destinations) & set(targets)
    kept = allocations[~allocations["county"].astype(str).str.upper().isin(exact_counties)].copy()
    exact_rows = pd.DataFrame(
        [
            {"county": county, "district": destinations[county], "alloc_votes": float(targets[county])}
            for county in sorted(exact_counties)
        ]
    )
    return pd.concat([kept, exact_rows], ignore_index=True)


def current_year() -> int:
    try:
        return int(sys.argv[sys.argv.index("--year") + 1])
    except (ValueError, IndexError):
        return 0


def current_lines_year() -> int:
    for flag in ("--district-lines-year", "--allocation-year"):
        try:
            return int(sys.argv[sys.argv.index(flag) + 1])
        except (ValueError, IndexError):
            continue
    return 0


def canonical_county_map(
    precinct_party: pd.DataFrame,
    county_non_geo_party: pd.DataFrame | None,
) -> dict[str, dict[str, int]] | None:
    state = {
        col: int(round(sum(county_targets(precinct_party, col, county_non_geo_party).values())))
        for col in PARTY_COLUMNS
    }
    state_total = sum(state.values())
    cache_key = (current_year(), state["dem_votes"], state["rep_votes"], state["other_votes"])
    if cache_key in _canonical_cache:
        return _canonical_cache[cache_key]
    matches: list[tuple[int, dict[str, dict[str, int]]]] = []
    for path in Path("data/contests").glob(f"*_{current_year()}.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        counties = payload.get("county_totals") or {}
        candidate = {
            col: sum(int(row.get(col, 0) or 0) for row in counties.values())
            for col in PARTY_COLUMNS
        }
        distance = sum(abs(candidate[col] - state[col]) for col in PARTY_COLUMNS)
        matches.append((distance, counties))
    matches.sort(key=lambda item: item[0])
    # Historical parsers can differ from canonical returns by a handful of
    # write-ins or fused-party votes. Match the unique nearest statewide party
    # vector, but reject anything farther than 0.1% of the statewide vote.
    result = None
    if matches and matches[0][0] <= max(25, round(state_total * 0.001)):
        if len(matches) == 1 or matches[0][0] < matches[1][0]:
            result = matches[0][1]
    _canonical_cache[cache_key] = result
    return result


def largest_remainder(values: dict[str, float], target: int) -> dict[str, int]:
    floors = {key: int(value // 1) for key, value in values.items()}
    remainder = int(target) - sum(floors.values())
    ranked = sorted(
        values,
        key=lambda key: (values[key] - floors[key], -int(key)),
        reverse=True,
    )
    if remainder < 0 or remainder > len(ranked):
        raise ValueError(f"Unexpected rounding remainder {remainder} for target {target}")
    for key in ranked[:remainder]:
        floors[key] += 1
    return floors


def integerize_counties(
    allocations: pd.DataFrame,
    targets: dict[str, float],
) -> dict[str, int]:
    district_totals: dict[str, int] = defaultdict(int)
    represented: set[str] = set()
    for county, group in allocations.groupby("county"):
        county = str(county).strip().upper()
        represented.add(county)
        values = {
            str(row.district).strip().lstrip("0") or "0": float(row.alloc_votes)
            for row in group.itertuples(index=False)
        }
        rounded = largest_remainder(values, int(round(float(targets.get(county, sum(values.values()))))))
        for district, votes in rounded.items():
            district_totals[district] += votes
    missing = {county: votes for county, votes in targets.items() if votes and county not in represented}
    if missing:
        raise ValueError(f"Counties with votes but no district allocation: {sorted(missing)}")
    return dict(district_totals)


def county_targets(
    precinct_party: pd.DataFrame,
    col: str,
    county_non_geo_party: pd.DataFrame | None,
) -> dict[str, float]:
    source = precinct_party[["precinct_id", col]].copy()
    source["county"] = source["precinct_id"].astype(str).str.split(" - ").str[0].str.strip().str.upper()
    source[col] = pd.to_numeric(source[col], errors="coerce").fillna(0.0)
    targets = {str(k): float(v) for k, v in source.groupby("county")[col].sum().items()}
    if county_non_geo_party is not None and not county_non_geo_party.empty:
        extra = county_non_geo_party[county_non_geo_party["party_group"] == col].copy()
        extra["votes"] = pd.to_numeric(extra["votes"], errors="coerce").fillna(0.0)
        for county, votes in extra.groupby("county")["votes"].sum().items():
            key = str(county).strip().upper()
            targets[key] = targets.get(key, 0.0) + float(votes)
    return targets


def canonical_targets(
    precinct_party: pd.DataFrame,
    col: str,
    county_non_geo_party: pd.DataFrame | None,
) -> dict[str, float]:
    canonical = canonical_county_map(precinct_party, county_non_geo_party)
    if canonical:
        return {str(county).upper(): float(row.get(col, 0) or 0) for county, row in canonical.items()}
    return county_targets(precinct_party, col, county_non_geo_party)


def reconcile_allocations_to_targets(
    allocations: pd.DataFrame,
    targets: dict[str, float],
    county_shares: pd.DataFrame,
) -> pd.DataFrame:
    current = allocations.groupby("county")["alloc_votes"].sum().to_dict()
    additions = []
    for county, target in targets.items():
        residual = float(target) - float(current.get(county, 0.0))
        if abs(residual) < 1e-7:
            continue
        shares = county_shares[county_shares["county"].astype(str).str.upper() == county]
        if shares.empty:
            raise ValueError(f"No county district shares for residual allocation: {county}")
        for row in shares.itertuples(index=False):
            additions.append({
                "county": county,
                "district": str(row.district),
                "alloc_votes": residual * float(row.share),
            })
    if additions:
        allocations = pd.concat([allocations, pd.DataFrame(additions)], ignore_index=True)
    return allocations.groupby(["county", "district"], as_index=False)["alloc_votes"].sum()


def fallback_allocations(
    rows: pd.DataFrame,
    county_shares: pd.DataFrame,
    precinct_bucket_shares: pd.DataFrame,
) -> list[pd.DataFrame]:
    if rows.empty:
        return []
    work = rows.copy()
    work["county"] = work["precinct_id"].astype(str).str.split(" - ").str[0].str.strip().str.upper()
    work["precinct"] = work["precinct_id"].astype(str).str.split(" - ").str[1].fillna("").str.strip().str.upper()
    work["bucket"] = work["precinct"].map(legacy.precinct_bucket_from_code)
    work["votes"] = pd.to_numeric(work["votes"], errors="coerce").fillna(0.0)
    grouped = work.groupby(["county", "bucket"], as_index=False)["votes"].sum()
    grouped = grouped.rename(columns={"votes": "source_votes"})

    frames: list[pd.DataFrame] = []
    bucket = grouped.merge(precinct_bucket_shares, on=["county", "bucket"], how="inner")
    assigned = bucket[["county", "bucket"]].drop_duplicates() if not bucket.empty else pd.DataFrame()
    if not bucket.empty:
        bucket["alloc_votes"] = bucket["source_votes"] * bucket["share"]
        frames.append(bucket[["county", "district", "alloc_votes"]])
    remaining = grouped
    if not assigned.empty:
        remaining = grouped.merge(assigned, on=["county", "bucket"], how="left", indicator=True)
        remaining = remaining[remaining["_merge"] == "left_only"].drop(columns="_merge")
    if not remaining.empty:
        remaining = remaining.groupby("county", as_index=False)["source_votes"].sum()
        county = remaining.merge(county_shares, on="county", how="left").dropna(subset=["district", "share"])
        county["alloc_votes"] = county["source_votes"] * county["share"]
        frames.append(county[["county", "district", "alloc_votes"]])
    return frames


def constrained_agg_party_to_scope(
    precinct_party: pd.DataFrame,
    crosswalk_df: pd.DataFrame,
    vap_df: pd.DataFrame,
    map_path,
    block_col: str,
    district_col: str,
    county_shares: pd.DataFrame,
    precinct_bucket_shares: pd.DataFrame,
    matched_precincts: set[str],
    county_non_geo_party: pd.DataFrame | None = None,
):
    district_map = legacy.load_district_map(map_path, block_col, district_col)
    district_count = district_map["district"].astype(str).nunique()
    scope = "state_house" if district_count > 80 else ("state_senate" if district_count > 30 else "congressional")
    target_year = current_lines_year()
    plan_key = component_plan_key(scope, target_year)
    exact_destinations = exact_county_destinations(plan_key)
    if plan_key:
        _component_audit[plan_key] = {
            "exact_counties": sorted(exact_destinations),
            "exact_county_count": len(exact_destinations),
            "method": "canonical whole-county component plus precinct/SF1-weighted split-county component",
        }
    normalized_ids = precinct_party["precinct_id"].astype(str).str.strip().str.upper()
    matched_count = int(normalized_ids.isin(matched_precincts).sum())
    output: dict[str, dict[str, int]] = {}

    for col in PARTY_COLUMNS:
        results = legacy.to_results_df(precinct_party, col)
        results["precinct_id"] = results["precinct_id"].astype(str).str.strip().str.upper()
        matched = results[results["precinct_id"].isin(matched_precincts)].copy()
        unmatched = results[~results["precinct_id"].isin(matched_precincts)].copy()
        frames: list[pd.DataFrame] = []
        if not matched.empty:
            shattered, _ = shatter_votes(matched, crosswalk_df, vap_df, precision=28)
            joined = shattered.merge(district_map, on="block_geoid20", how="inner")
            joined["county"] = joined["precinct_id"].astype(str).str.split(" - ").str[0].str.strip().str.upper()
            geographic = joined.groupby(["county", "district"], as_index=False)["block_votes_raw"].sum()
            geographic["alloc_votes"] = geographic["block_votes_raw"].map(float)
            frames.append(geographic[["county", "district", "alloc_votes"]])
        frames.extend(fallback_allocations(unmatched, county_shares, precinct_bucket_shares))
        if county_non_geo_party is not None and not county_non_geo_party.empty:
            nongeo = county_non_geo_party[county_non_geo_party["party_group"] == col][["county", "votes"]].copy()
            if not nongeo.empty:
                nongeo["county"] = nongeo["county"].astype(str).str.strip().str.upper()
                nongeo = nongeo.merge(county_shares, on="county", how="left").dropna(subset=["district", "share"])
                nongeo["alloc_votes"] = pd.to_numeric(nongeo["votes"], errors="coerce").fillna(0.0) * nongeo["share"]
                frames.append(nongeo[["county", "district", "alloc_votes"]])
        allocations = pd.concat(frames, ignore_index=True).groupby(
            ["county", "district"], as_index=False
        )["alloc_votes"].sum()
        targets = canonical_targets(precinct_party, col, county_non_geo_party)
        allocations = reconcile_allocations_to_targets(allocations, targets, county_shares)
        allocations = isolate_exact_county_components(allocations, targets, exact_destinations)
        output[col] = integerize_counties(
            allocations,
            targets,
        )
    return output["dem_votes"], output["rep_votes"], output["other_votes"], matched_count, len(precinct_party)


def constrained_weighted_aggregate(
    precinct_party: pd.DataFrame,
    scope_weights: dict,
    *,
    county_shares: pd.DataFrame | None = None,
    county_non_geo_party: pd.DataFrame | None = None,
):
    plan_key = component_plan_key(
        str(scope_weights.get("district_type") or ""),
        int(scope_weights.get("target_year") or 0),
    )
    exact_destinations = exact_county_destinations(plan_key)
    if plan_key:
        _component_audit[plan_key] = {
            "exact_counties": sorted(exact_destinations),
            "exact_county_count": len(exact_destinations),
            "method": "canonical whole-county component plus precinct/SF1-weighted split-county component",
        }
    precincts = {
        str(key).strip().upper(): value
        for key, value in (scope_weights.get("precincts") or {}).items()
        if isinstance(value, list)
    }
    aliases = legacy.build_sbe2006_weight_alias_lookup(set(precincts))

    def resolve(value: str) -> str | None:
        key = legacy._norm_spaces(value)
        for alias in legacy.sbe2006_precinct_key_aliases(key):
            if alias in precincts:
                return alias
            hit = aliases.get(alias) or aliases.get(legacy._compact_token(alias))
            if hit:
                return hit
        return None

    resolved = precinct_party["precinct_id"].astype(str).map(resolve)
    matched_count = int(resolved.notna().sum())
    output: dict[str, dict[str, int]] = {}
    for col in PARTY_COLUMNS:
        rows = precinct_party[["precinct_id", col]].copy()
        rows["resolved"] = rows["precinct_id"].astype(str).map(resolve)
        rows["county"] = rows["precinct_id"].astype(str).str.split(" - ").str[0].str.strip().str.upper()
        rows["votes"] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
        allocations: list[dict[str, object]] = []
        for row in rows[rows["resolved"].notna()].itertuples(index=False):
            for entry in precincts.get(str(row.resolved), []):
                share = float((entry or {}).get("share") or 0.0)
                if share > 0:
                    allocations.append({
                        "county": row.county,
                        "district": str((entry or {}).get("district", "")).strip().lstrip("0") or "0",
                        "alloc_votes": float(row.votes) * share,
                    })
        unmatched = rows[rows["resolved"].isna()][["precinct_id", "votes"]]
        if county_shares is not None:
            allocations.extend(
                pd.concat(fallback_allocations(unmatched, county_shares, pd.DataFrame(
                    columns=["county", "bucket", "district", "share"]
                )), ignore_index=True).to_dict("records")
                if not unmatched.empty else []
            )
        if county_non_geo_party is not None and county_shares is not None:
            nongeo = county_non_geo_party[county_non_geo_party["party_group"] == col][["county", "votes"]].copy()
            nongeo = nongeo.merge(county_shares, on="county", how="left").dropna(subset=["district", "share"])
            for row in nongeo.itertuples(index=False):
                allocations.append({"county": str(row.county).upper(), "district": str(row.district), "alloc_votes": float(row.votes) * float(row.share)})
        frame = pd.DataFrame(allocations).groupby(["county", "district"], as_index=False)["alloc_votes"].sum()
        targets = canonical_targets(precinct_party, col, county_non_geo_party)
        frame = reconcile_allocations_to_targets(frame, targets, county_shares)
        frame = isolate_exact_county_components(frame, targets, exact_destinations)
        output[col] = integerize_counties(frame, targets)
    return output["dem_votes"], output["rep_votes"], output["other_votes"], matched_count, len(precinct_party)


def main() -> None:
    legacy.agg_party_to_scope = constrained_agg_party_to_scope
    legacy.aggregate_precinct_party_with_district_weights = constrained_weighted_aggregate
    legacy.main()
    try:
        output_dir = Path(sys.argv[sys.argv.index("--district-contests-dir") + 1])
        year = current_year()
    except (ValueError, IndexError):
        return
    for path in output_dir.glob(f"*_{year}.json"):
        if path.name == "manifest.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.setdefault("meta", {})
        meta["county_constrained_rounding"] = True
        meta["county_constrained_source"] = (
            "Canonical county contest totals with legacy precinct/SF1/VAP district weights"
        )
        meta["county_constrained_method"] = (
            "Add canonical whole-county components directly; allocate only split-county "
            "components with precinct/SF1 weights; largest-remainder round each county/party "
            "bucket; then sum county contributions into districts."
        )
        scope = str(payload.get("scope") or "")
        plan_key = component_plan_key(scope, int(meta.get("district_lines_year") or 0))
        audit = _component_audit.get(plan_key or "")
        if audit:
            meta["mixed_county_component_separation"] = audit
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
