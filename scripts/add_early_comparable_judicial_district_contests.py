#!/usr/bin/env python3
"""District-aggregate newly added early judicial seat_NN contests only.

Reads seat-numbered precinct slices already written under data/contests for
2000/2002/2004/2006, then builds matching district overlays into
data/district_contests (2022 lines / SBE2006 weights, same path as live early
statewide contests). Never overwrites existing district JSON files and never
rewrites precinct contest slices.

Usage:
  python scripts/add_early_comparable_judicial_district_contests.py
  python scripts/add_early_comparable_judicial_district_contests.py --dry-run
  python scripts/add_early_comparable_judicial_district_contests.py --years 2004,2006
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_district_contests_from_batch_shatter as builder  # noqa: E402
from build_district_contests_from_batch_shatter import (  # noqa: E402
    aggregate_precinct_party_with_district_weights,
    apply_county_share_overrides,
    build_auto_precinct_overrides,
    build_county_shares,
    build_payload,
    build_precinct_bucket_shares,
    build_precinct_party_votes,
    clean_precinct_name,
    load_allocation_weights,
    load_district_map,
    load_precinct_overrides,
    load_sbe2006_district_weights,
    load_sbe_precinct_code_map,
    resolve_vintage_match_crosswalk,
    select_sbe2006_district_weight_scopes,
)
from shatter_precinct_votes_vap import load_crosswalk, load_vap  # noqa: E402

SEAT_FILE_RE = re.compile(
    r"^(?P<ct>nc_(?:supreme_court_(?:chief_justice|associate_justice)|court_of_appeals_judge)_seat_\d{2})_(?P<year>200[0246])\.json$"
)
DEFAULT_YEARS = (2000, 2002, 2004, 2006)
SCOPES = ("state_house", "state_senate", "congressional")


def find_general_precinct_csv(year: int) -> Path:
    year_dir = ROOT / "data" / str(year)
    matches = sorted(year_dir.glob("*__nc__general__precinct.csv"))
    if not matches:
        raise FileNotFoundError(f"No general precinct CSV under {year_dir}")
    # Prefer November generals (YYYY11...) over primaries (e.g. 20020910).
    november = [p for p in matches if p.name.startswith(f"{year}11")]
    pool = november or matches
    return max(pool, key=lambda p: p.stat().st_size)


def discover_targets(contests_dir: Path, years: set[int]) -> list[dict]:
    out: list[dict] = []
    for path in sorted(contests_dir.glob("nc_*_seat_*_200*.json")):
        m = SEAT_FILE_RE.match(path.name)
        if not m:
            continue
        year = int(m.group("year"))
        if year not in years:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        office = str((payload.get("meta") or {}).get("office") or "").strip()
        contest_type = str(payload.get("contest_type") or m.group("ct")).strip()
        if not office or not contest_type:
            print(f"  skip {path.name}: missing office/contest_type")
            continue
        out.append(
            {
                "year": year,
                "contest_type": contest_type,
                "office": office,
                "contest_file": path.name,
            }
        )
    return out


def district_paths(out_dir: Path, contest_type: str, year: int) -> dict[str, Path]:
    return {
        scope: out_dir / f"{scope}_{contest_type}_{year}.json"
        for scope in SCOPES
    }


def rebuild_district_manifest(out_dir: Path) -> None:
    manifest = []
    for p in sorted(out_dir.glob("*.json")):
        if p.name == "manifest.json":
            continue
        parts = p.stem.split("_")
        if len(parts) < 3:
            continue
        if parts[0] == "state" and len(parts) >= 4:
            scope = "_".join(parts[0:2])
            contest_type = "_".join(parts[2:-1])
        else:
            scope = parts[0]
            contest_type = "_".join(parts[1:-1])
        try:
            year = int(parts[-1])
        except ValueError:
            continue
        if scope not in SCOPES:
            continue
        manifest.append(
            {
                "year": year,
                "scope": scope,
                "contest_type": contest_type,
                "file": p.name,
            }
        )
    manifest.sort(key=lambda x: (x["year"], x["scope"], x["contest_type"]))
    (out_dir / "manifest.json").write_text(
        json.dumps({"files": manifest}, indent=2) + "\n", encoding="utf-8"
    )


def agg_party_to_scope(
    precinct_party: pd.DataFrame,
    crosswalk_df: pd.DataFrame,
    vap_df: pd.DataFrame,
    district_file: Path,
    block_col: str,
    district_col: str,
    county_shares: dict,
    bucket_shares: dict,
    matched_precincts: set[str],
    county_non_geo_party=None,
):
    return builder.agg_party_to_scope(
        precinct_party,
        crosswalk_df,
        vap_df,
        district_file,
        block_col,
        district_col,
        county_shares,
        bucket_shares,
        matched_precincts,
        county_non_geo_party=county_non_geo_party,
    )


def process_year(
    *,
    year: int,
    targets: list[dict],
    out_dir: Path,
    dry_run: bool,
    skip_existing: bool,
) -> dict:
    print(f"\n=== {year} ({len(targets)} contests) ===")
    results_csv = find_general_precinct_csv(year)
    print(f"results: {results_csv.as_posix()}")

    builder._JUDICIAL_PARTY_OVERRIDE_CACHE = None

    # Match live early statewide district overlays (governor_2000 style).
    allocation_year = 2022
    district_lines_year = 2022
    district_lines_label = "2022 lines"
    house_file = ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv"
    senate_file = ROOT / "data/tmp/block_assign_extract/SL 2022-2.csv"
    cd_file = ROOT / "data/tmp/block_assign_extract/NC_CD118.csv"
    vap_csv = ROOT / "data/census/block_vap_2020_nc.csv"
    allocation_weights_json = ROOT / "data/mappings/allocation_weights.json"
    sbe2006_weights_json = ROOT / "data/mappings/sbe2006_to_modern_district_weights.json"
    precinct_overrides_csv = ROOT / "data/mappings/precinct_key_overrides.csv"
    sbe_shp = ROOT / "data/Precincts2006Gen/Precincts2006Gen.shp"
    target_crosswalk = ROOT / "data/crosswalks/block20_to_onemap_2025_12.csv"

    match_crosswalk = resolve_vintage_match_crosswalk(year, fallback=target_crosswalk)
    print(f"match crosswalk: {match_crosswalk.as_posix()}")

    sbe_map = load_sbe_precinct_code_map(sbe_shp) if sbe_shp.exists() else {}
    clean_precinct_name._sbe_map = sbe_map  # type: ignore[attr-defined]
    build_auto_precinct_overrides._sbe_map = sbe_map  # type: ignore[attr-defined]

    src = pd.read_csv(results_csv, dtype=str, low_memory=False)
    crosswalk_df = load_crosswalk(match_crosswalk, "precinct_id", "block_geoid20")
    matched_precincts = set(crosswalk_df["precinct_id"].astype(str).str.strip().str.upper().unique())
    src_precinct_ids = (
        src["county"].astype(str).str.strip().str.upper()
        + " - "
        + src["precinct"].astype(str).str.strip().str.upper()
    )
    auto_overrides = build_auto_precinct_overrides(src_precinct_ids, matched_precincts)
    manual_overrides = load_precinct_overrides(precinct_overrides_csv, year)
    precinct_overrides = {**auto_overrides, **manual_overrides}

    if dry_run:
        for t in targets:
            paths = district_paths(out_dir, t["contest_type"], year)
            existing = [s for s, p in paths.items() if p.exists()]
            action = "skip_existing" if (skip_existing and len(existing) == 3) else "create"
            print(f"  {action} {t['contest_type']} <- {t['office']} existing={existing}")
        return {"year": year, "written": 0, "skipped_existing": 0, "skipped_empty": 0}

    vap_df = load_vap(vap_csv, "block_geoid20", "vap_count")
    allocation_weights = load_allocation_weights(allocation_weights_json)
    house_map = load_district_map(house_file, "Block", "District")
    senate_map = load_district_map(senate_file, "Block", "District")
    cd_map = load_district_map(cd_file, "GEOID", "CDFP")
    min_county_share = 0.01
    house_shares = apply_county_share_overrides(
        build_county_shares(crosswalk_df, vap_df, house_map),
        year=allocation_year,
        scope="state_house",
        allocation_weights=allocation_weights,
        min_county_share=min_county_share,
    )
    house_bucket_shares = build_precinct_bucket_shares(crosswalk_df, vap_df, house_map)
    senate_shares = apply_county_share_overrides(
        build_county_shares(crosswalk_df, vap_df, senate_map),
        year=allocation_year,
        scope="state_senate",
        allocation_weights=allocation_weights,
        min_county_share=min_county_share,
    )
    senate_bucket_shares = build_precinct_bucket_shares(crosswalk_df, vap_df, senate_map)
    cd_shares = apply_county_share_overrides(
        build_county_shares(crosswalk_df, vap_df, cd_map),
        year=allocation_year,
        scope="congressional",
        allocation_weights=allocation_weights,
        min_county_share=min_county_share,
    )
    cd_bucket_shares = build_precinct_bucket_shares(crosswalk_df, vap_df, cd_map)

    sbe2006_weight_scopes = select_sbe2006_district_weight_scopes(
        load_sbe2006_district_weights(sbe2006_weights_json),
        weight_set="auto",
        allocation_year=allocation_year,
        cd_file=cd_file,
    )
    if sbe2006_weight_scopes:
        print(
            "SBE2006 district chain scopes: "
            + ", ".join(f"{k}={v.get('plan_id', '')}" for k, v in sorted(sbe2006_weight_scopes.items()))
        )

    written = 0
    skipped_existing = 0
    skipped_empty = 0
    out_dir.mkdir(parents=True, exist_ok=True)

    for t in targets:
        contest_type = t["contest_type"]
        office = t["office"]
        paths = district_paths(out_dir, contest_type, year)
        if skip_existing and all(p.exists() for p in paths.values()):
            print(f"  skip existing {contest_type}")
            skipped_existing += 1
            continue

        print(f"  build {office} -> {contest_type}")
        precinct_party, dem_candidate, rep_candidate = build_precinct_party_votes(
            src, office, precinct_overrides=precinct_overrides, election_year=year
        )
        if precinct_party.empty:
            print("    empty precinct party votes")
            skipped_empty += 1
            continue
        dem_tot = float(precinct_party["dem_votes"].sum())
        rep_tot = float(precinct_party["rep_votes"].sum())
        if dem_tot <= 0 or rep_tot <= 0:
            print(f"    skip not two-party contested dem={dem_tot:.0f} rep={rep_tot:.0f}")
            skipped_empty += 1
            continue

        if "state_house" in sbe2006_weight_scopes:
            dem_h, rep_h, oth_h, matched, total = aggregate_precinct_party_with_district_weights(
                precinct_party, sbe2006_weight_scopes["state_house"], county_shares=house_shares
            )
        else:
            dem_h, rep_h, oth_h, matched, total = agg_party_to_scope(
                precinct_party,
                crosswalk_df,
                vap_df,
                house_file,
                "Block",
                "District",
                house_shares,
                house_bucket_shares,
                matched_precincts,
            )
        if "state_senate" in sbe2006_weight_scopes:
            dem_s, rep_s, oth_s, _, _ = aggregate_precinct_party_with_district_weights(
                precinct_party, sbe2006_weight_scopes["state_senate"], county_shares=senate_shares
            )
        else:
            dem_s, rep_s, oth_s, _, _ = agg_party_to_scope(
                precinct_party,
                crosswalk_df,
                vap_df,
                senate_file,
                "Block",
                "District",
                senate_shares,
                senate_bucket_shares,
                matched_precincts,
            )
        if "congressional" in sbe2006_weight_scopes:
            dem_c, rep_c, oth_c, _, _ = aggregate_precinct_party_with_district_weights(
                precinct_party, sbe2006_weight_scopes["congressional"], county_shares=cd_shares
            )
        else:
            dem_c, rep_c, oth_c, _, _ = agg_party_to_scope(
                precinct_party,
                crosswalk_df,
                vap_df,
                cd_file,
                "GEOID",
                "CDFP",
                cd_shares,
                cd_bucket_shares,
                matched_precincts,
            )

        def _plan(scope_name: str) -> str | None:
            payload = sbe2006_weight_scopes.get(scope_name)
            if not payload:
                return None
            return str(payload.get("plan_id") or payload.get("scope") or "").strip() or None

        def _weights_json(scope_name: str) -> str | None:
            return sbe2006_weights_json.as_posix() if scope_name in sbe2006_weight_scopes else None

        payloads = {
            "state_house": build_payload(
                year=year,
                scope="state_house",
                contest_type=contest_type,
                office_label=office,
                nongeo_allocation_mode="precinct_candidate",
                dem_map=dem_h,
                rep_map=rep_h,
                oth_map=oth_h,
                dem_candidate=dem_candidate,
                rep_candidate=rep_candidate,
                matched=matched,
                total=total,
                match_crosswalk=match_crosswalk.as_posix(),
                target_crosswalk=target_crosswalk.as_posix(),
                district_weights_json=_weights_json("state_house"),
                district_weight_plan=_plan("state_house"),
                district_lines_year=district_lines_year,
                district_lines_label=district_lines_label,
            ),
            "state_senate": build_payload(
                year=year,
                scope="state_senate",
                contest_type=contest_type,
                office_label=office,
                nongeo_allocation_mode="precinct_candidate",
                dem_map=dem_s,
                rep_map=rep_s,
                oth_map=oth_s,
                dem_candidate=dem_candidate,
                rep_candidate=rep_candidate,
                matched=matched,
                total=total,
                match_crosswalk=match_crosswalk.as_posix(),
                target_crosswalk=target_crosswalk.as_posix(),
                district_weights_json=_weights_json("state_senate"),
                district_weight_plan=_plan("state_senate"),
                district_lines_year=district_lines_year,
                district_lines_label=district_lines_label,
            ),
            "congressional": build_payload(
                year=year,
                scope="congressional",
                contest_type=contest_type,
                office_label=office,
                nongeo_allocation_mode="precinct_candidate",
                dem_map=dem_c,
                rep_map=rep_c,
                oth_map=oth_c,
                dem_candidate=dem_candidate,
                rep_candidate=rep_candidate,
                matched=matched,
                total=total,
                match_crosswalk=match_crosswalk.as_posix(),
                target_crosswalk=target_crosswalk.as_posix(),
                district_weights_json=_weights_json("congressional"),
                district_weight_plan=_plan("congressional"),
                district_lines_year=district_lines_year,
                district_lines_label=district_lines_label,
            ),
        }

        for scope, payload in payloads.items():
            out_path = paths[scope]
            if skip_existing and out_path.exists():
                continue
            out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            written += 1
        print(
            f"    candidates {dem_candidate!r}/{rep_candidate!r} "
            f"D/R={dem_tot:.0f}/{rep_tot:.0f} match={matched}/{total}"
        )

    return {
        "year": year,
        "written": written,
        "skipped_existing": skipped_existing,
        "skipped_empty": skipped_empty,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="District-aggregate newly added early judicial seat_NN contests only."
    )
    p.add_argument(
        "--years",
        default=",".join(str(y) for y in DEFAULT_YEARS),
        help="Comma-separated years (default: 2000,2002,2004,2006).",
    )
    p.add_argument("--contests-dir", type=Path, default=ROOT / "data/contests")
    p.add_argument("--district-contests-dir", type=Path, default=ROOT / "data/district_contests")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing district JSON files (default: skip existing).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    years = {int(part.strip()) for part in str(args.years).split(",") if part.strip()}
    if not years:
        raise SystemExit("No years provided")

    targets = discover_targets(Path(args.contests_dir), years)
    if not targets:
        print("No seat_NN contest files found for requested years.")
        return 1

    by_year: dict[int, list[dict]] = defaultdict(list)
    for t in targets:
        by_year[int(t["year"])].append(t)

    print(f"Discovered {len(targets)} precinct contest targets across {sorted(by_year)}")
    summaries = []
    for year in sorted(by_year):
        summaries.append(
            process_year(
                year=year,
                targets=by_year[year],
                out_dir=Path(args.district_contests_dir),
                dry_run=bool(args.dry_run),
                skip_existing=not bool(args.overwrite),
            )
        )

    if not args.dry_run:
        rebuild_district_manifest(Path(args.district_contests_dir))
        print(f"Updated {Path(args.district_contests_dir) / 'manifest.json'}")

    print("\n=== summary ===")
    for s in summaries:
        print(
            f"{s['year']}: wrote={s['written']} existing={s['skipped_existing']} "
            f"empty/skip={s['skipped_empty']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
