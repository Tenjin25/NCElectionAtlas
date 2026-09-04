#!/usr/bin/env python3
"""Build calibrated NCSBE precinct-sort results for NC congressional and legislative plans."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_ncsbe2024_house_benchmarks as base  # noqa: E402
import build_ncsbe_mggg_senate_congress_benchmarks as modern  # noqa: E402


DEFAULT_OUTPUT = ROOT / "data/reports/ncsbe_all_plans_precinct_sort_benchmarks.json"
DEFAULT_COMPARE = ROOT / "data/reports/ncsbe_all_plans_precinct_sort_compare.json"
YEARS = (2016, 2018, 2020, 2022, 2024)
PLAN_TARGETS = {
    "2022_congressional": ("congressional", ROOT / "data/district_contests", modern.PLAN_SPECS["2022_congressional"]),
    "2024_congressional": ("congressional", ROOT / "data/district_contests_2024_lines", modern.PLAN_SPECS["2024_congressional"]),
    "2026_congressional": ("congressional", ROOT / "data/district_contests_2026_lines", modern.PLAN_SPECS["2026_congressional"]),
    "2022_state_senate": ("state_senate", ROOT / "data/district_contests", modern.PLAN_SPECS["2022_state_senate"]),
    "2024_state_senate": ("state_senate", ROOT / "data/district_contests_2024_lines", modern.PLAN_SPECS["2024_state_senate"]),
    "2022_state_house": ("state_house", ROOT / "data/district_contests", {"assignment": ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv", "block_col": "Block", "district_col": "District", "plan_id": "SL 2022-4"}),
    "2024_state_house": ("state_house", ROOT / "data/district_contests_2024_lines", {"assignment": ROOT / "data/crosswalks/block20_to_2024_state_house.csv", "block_col": "block_geoid20", "district_col": "district", "plan_id": "SL 2023-149"}),
}


def clean(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.replace("\x00", "", regex=False).str.strip().str.upper()


def mappings(year: int) -> tuple[dict[str, str], dict[str, str], dict[tuple[str, str], str], dict[str, str], Path]:
    _, offices, overrides, crosswalk = modern.prepare_ncsbe(year)
    contest_map = {re.sub(r"\s+", " ", office.strip().upper()): f"{slug}_{year}" for office, slug in offices}
    contest_map = {
        office: contest
        for office, contest in contest_map.items()
        if any((live_dir / f"{scope}_{contest}.json").exists() for scope, live_dir, _ in PLAN_TARGETS.values())
    }
    candidate_map: dict[tuple[str, str], str] = {}
    for contest in contest_map.values():
        sample_path = next(live_dir / f"{scope}_{contest}.json" for scope, live_dir, _ in PLAN_TARGETS.values() if (live_dir / f"{scope}_{contest}.json").exists())
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
        sample = next(iter(payload["general"]["results"].values()))
        for field, bucket in (("dem_candidate", "dem"), ("rep_candidate", "rep")):
            name = str(sample.get(field) or "").strip().upper()
            if name:
                candidate_map[(contest, name)] = bucket
    source = pd.read_csv(modern.NCSBE_FILES[year], dtype=str, usecols=["office", "candidate"], low_memory=False)
    source["office"] = clean(source["office"])
    source["candidate"] = clean(source["candidate"])
    candidate_contests: dict[str, set[str]] = {}
    for row in source[source["office"].isin(contest_map)].drop_duplicates().itertuples(index=False):
        candidate_contests.setdefault(row.candidate, set()).add(contest_map[row.office])
    candidate_contest_map = {name: next(iter(values)) for name, values in candidate_contests.items() if name and len(values) == 1}
    normalized_overrides = {str(key).strip().upper(): str(value).strip().upper() for key, value in overrides.items()}
    if year == 2024:
        normalized_overrides.update({
            "UNION - 0020B": "UNION - 020B",
            "UNION - 0044": "UNION - 044",
            "UNION - 0045": "UNION - 045",
        })
    return contest_map, candidate_contest_map, candidate_map, normalized_overrides, crosswalk


def resolve_contest(title: str, contest_map: dict[str, str]) -> str | None:
    if title in contest_map:
        return contest_map[title]
    matches = {contest for office, contest in contest_map.items() if office.startswith(title) or title.startswith(office)}
    return next(iter(matches)) if len(matches) == 1 else None


def bucket_for(contest: str, candidate: str, party: str, candidate_map: dict[tuple[str, str], str]) -> str:
    normalized_candidate = str(candidate or "").strip().upper()
    # In the 2018 Supreme Court race, NCSBE labels both Barbara Jackson and
    # spoiler Christopher Anglin as REP. Jackson is the principal Republican
    # candidate used by the live JSON; Anglin belongs in the other bucket.
    if contest == "nc_supreme_court_associate_justice_seat_01_2018" and "ANGLIN" in normalized_candidate:
        return "other"
    normalized_party = str(party or "").strip().upper()
    if normalized_party == "DEM":
        return "dem"
    if normalized_party == "REP":
        return "rep"
    return candidate_map.get((contest, normalized_candidate), "other")


def load_sort(paths: list[Path], contest_map: dict[str, str], candidate_contest_map: dict[str, str], candidate_map: dict[tuple[str, str], str], overrides: dict[str, str], chunksize: int) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for path in paths:
        columns = pd.read_csv(path, sep="\t", nrows=0, encoding="utf-8-sig").columns.tolist()
        precinct_column = "precinct_code" if "precinct_code" in columns else "precinct_name"
        usecols = ["county", "result_type_lbl", "contest_title", precinct_column, "candidate_name", "candidate_party_lbl", "vote_ct"]
        for chunk in pd.read_csv(path, sep="\t", dtype=str, encoding="utf-8-sig", usecols=usecols, chunksize=chunksize, low_memory=False):
            chunk["result_type_lbl"] = clean(chunk["result_type_lbl"])
            chunk["contest_title"] = clean(chunk["contest_title"])
            chunk["candidate_name"] = clean(chunk["candidate_name"])
            chunk["contest"] = chunk["contest_title"].map(lambda title: resolve_contest(title, contest_map))
            chunk["contest"] = chunk["contest"].fillna(chunk["candidate_name"].map(candidate_contest_map))
            chunk = chunk[(chunk["result_type_lbl"] == "STD") & chunk["contest"].notna() & ~chunk["candidate_name"].isin({"UNDER VOTE", "OVER VOTE"})].copy()
            if chunk.empty:
                continue
            chunk["county"] = clean(chunk["county"])
            chunk[precinct_column] = clean(chunk[precinct_column])
            if precinct_column == "precinct_name":
                # The 2016 export's precinct_cd is an internal numeric ID; the
                # canonical election precinct code is the prefix of precinct_name.
                chunk[precinct_column] = chunk[precinct_column].str.split("_", n=1).str[0]
            chunk["precinct_id"] = chunk["county"] + " - " + chunk[precinct_column]
            chunk["precinct_id"] = chunk["precinct_id"].replace(overrides)
            chunk["bucket"] = chunk.apply(lambda row: bucket_for(row["contest"], row["candidate_name"], row["candidate_party_lbl"], candidate_map), axis=1)
            chunk["votes"] = pd.to_numeric(chunk["vote_ct"], errors="raise")
            pieces.append(chunk.groupby(["county", "precinct_id", "contest", "bucket"], as_index=False)["votes"].sum())
    if not pieces:
        raise ValueError("No matching precinct-sort contests")
    return pd.concat(pieces, ignore_index=True).groupby(["county", "precinct_id", "contest", "bucket"], as_index=False)["votes"].sum()


def load_official(year: int, contest_map: dict[str, str], candidate_map: dict[tuple[str, str], str]) -> pd.DataFrame:
    path = modern.NCSBE_FILES[year]
    frame = pd.read_csv(path, dtype=str, usecols=["county", "office", "candidate", "party", "votes"], low_memory=False)
    frame["office"] = clean(frame["office"])
    frame = frame[frame["office"].isin(contest_map)].copy()
    frame["county"] = clean(frame["county"])
    frame["contest"] = frame["office"].map(contest_map)
    frame["candidate"] = clean(frame["candidate"])
    frame["bucket"] = frame.apply(lambda row: bucket_for(row["contest"], row["candidate"], row["party"], candidate_map), axis=1)
    frame["official_votes"] = pd.to_numeric(frame["votes"], errors="raise")
    return frame.groupby(base.KEYS, as_index=False)["official_votes"].sum()


def fill_missing_sort_cells(precinct: pd.DataFrame, official: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    observed = precinct.groupby(base.KEYS, as_index=False)["votes"].sum().rename(columns={"votes": "sorted_votes"})
    missing = official.merge(observed, on=base.KEYS, how="left").fillna({"sorted_votes": 0})
    missing = missing[(missing["official_votes"] > 0) & (missing["sorted_votes"] <= 0)].copy()
    additions: list[pd.DataFrame] = []
    audit: list[dict[str, Any]] = []
    totals = precinct.groupby(["county", "precinct_id", "contest"], as_index=False)["votes"].sum()
    for row in missing.itertuples(index=False):
        basis = totals[(totals["county"] == row.county) & (totals["contest"] == row.contest)].copy()
        denominator = float(basis["votes"].sum())
        if denominator <= 0:
            raise ValueError(f"No geographic basis for missing precinct-sort cell: {row}")
        basis["votes"] = basis["votes"] * float(row.official_votes) / denominator
        basis["bucket"] = row.bucket
        additions.append(basis[["county", "precinct_id", "contest", "bucket", "votes"]])
        audit.append({"county": row.county, "contest": row.contest, "bucket": row.bucket, "official_votes": int(row.official_votes), "method": "distributed by total precinct contest votes"})
    return (pd.concat([precinct, *additions], ignore_index=True) if additions else precinct), audit


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct", "winner")}


def exact_ncga_district(meta: dict[str, Any], district: str) -> bool:
    if meta.get("ncga_statpack_calibrated"):
        return True
    targeted = {str(value) for value in meta.get("targeted_ncga_statpack_districts", [])}
    shared = {str(value) for value in meta.get("ncga_shared_districts", [])}
    return str(district) in targeted or str(district) in shared


def add_stable_precinct_fallbacks(block_precinct: pd.DataFrame) -> pd.DataFrame:
    """Add block lineage for real precincts omitted from a historical SBE bridge."""
    wanted = {
        ROOT / "data/crosswalks/block20_to_sbe_2015.csv": {"HENDERSON - CV"},
        ROOT / "data/crosswalks/block20_to_sbe_2024.csv": {
            "BURKE - 0071", "BURKE - 0072", "CHATHAM - MON113",
            "MARTIN - GRF", "MARTIN - GSN", "MARTIN - HMT", "MARTIN - JMV",
            "MARTIN - RBV", "MARTIN - WM1", "MARTIN - WM2", "NEW HANOVER - W33",
        },
        ROOT / "data/crosswalks/block20_to_onemap_2025.csv": {"BUNCOMBE - 681"},
    }
    pieces = [block_precinct]
    for path, precinct_ids in wanted.items():
        fallback = pd.read_csv(path, dtype=str, usecols=["block_geoid20", "precinct_id"])
        fallback["block_geoid20"] = fallback["block_geoid20"].astype(str).str.zfill(15)
        fallback["precinct_id"] = clean(fallback["precinct_id"])
        pieces.append(fallback[fallback["precinct_id"].isin(precinct_ids)])
    combined = pd.concat(pieces, ignore_index=True).drop_duplicates(["block_geoid20", "precinct_id"])
    # W32 appears in the 2022 election export but not the available SBE geometry.
    # Its ballot districts (CD-7, SD-7, HD-20) match adjacent W33; copy only W33's
    # district-weight lineage as an explicit proxy for the missing precinct.
    w32 = combined[combined["precinct_id"] == "NEW HANOVER - W33"].copy()
    w32["precinct_id"] = "NEW HANOVER - W32"
    return pd.concat([combined, w32], ignore_index=True).drop_duplicates(["block_geoid20", "precinct_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=list(YEARS))
    parser.add_argument("--download-root", type=Path, default=ROOT / "downloads/ncsbe")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--compare-output", type=Path, default=DEFAULT_COMPARE)
    parser.add_argument("--chunksize", type=int, default=300_000)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.compare_output = args.compare_output.resolve()

    vap = pd.read_csv(ROOT / "data/census/block_vap_2020_nc.csv", dtype={"block_geoid20": str})[["block_geoid20", "vap_count"]]
    vap["block_geoid20"] = vap["block_geoid20"].astype(str).str.zfill(15)
    years: dict[str, Any] = {}
    comparison_rows: list[dict[str, Any]] = []
    for year in args.years:
        contest_map, candidate_contest_map, candidate_map, overrides, crosswalk_path = mappings(year)
        paths = sorted((args.download_root / f"{year}_precinct_sort").glob("*.txt"))
        if not paths:
            raise FileNotFoundError(f"No precinct-sort files for {year}")
        precinct = load_sort(paths, contest_map, candidate_contest_map, candidate_map, overrides, args.chunksize)
        official = load_official(year, contest_map, candidate_map)
        precinct, missing_cell_fallbacks = fill_missing_sort_cells(precinct, official)
        reconciled, reconciliation = base.reconcile_to_official(precinct, official)
        block_precinct = modern.load_crosswalk(crosswalk_path, "precinct_id", "block_geoid20")
        block_precinct = add_stable_precinct_fallbacks(block_precinct)
        plan_outputs: dict[str, Any] = {}
        for plan_name, (scope, live_dir, spec) in PLAN_TARGETS.items():
            plan = modern.load_assignment(spec)
            weights, _ = modern.build_weights(block_precinct, plan, vap)
            district_count = 14 if scope == "congressional" else (50 if scope == "state_senate" else 120)
            results, audit = base.project(
                reconciled, weights, official, district_count=district_count,
                contests=sorted(contest_map.values()),
            )
            plan_outputs[plan_name] = {"scope": scope, "live_dir": live_dir.relative_to(ROOT).as_posix(), "plan_id": spec.get("plan_id"), "audit": audit, "results": results}
            for contest, districts in sorted(results.items()):
                live_path = live_dir / f"{scope}_{contest}.json"
                if not live_path.exists():
                    continue
                payload = json.loads(live_path.read_text(encoding="utf-8"))
                live = payload["general"]["results"]
                meta = payload.get("meta") or {}
                for district, values in districts.items():
                    current = snapshot(live[district])
                    after = snapshot(values)
                    comparison_rows.append({"year": year, "plan": plan_name, "scope": scope, "contest": contest, "district": district, "file": live_path.relative_to(ROOT).as_posix(), "preserve_exact_ncga": exact_ncga_district(meta, district), "current": current, "calibrated_precinct_sort": after, "delta": {key: after[key] - current[key] for key in ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct")}})
        years[str(year)] = {
            "source_files": [path.relative_to(ROOT).as_posix() for path in paths],
            "official_totals_source": modern.NCSBE_FILES[year].relative_to(ROOT).as_posix(),
            "crosswalk": modern.source_path_relative(crosswalk_path),
            "contests": sorted({contest for plan_output in plan_outputs.values() for contest in plan_output["results"]}),
            "reconciliation": reconciliation,
            "missing_sort_cell_fallbacks": missing_cell_fallbacks,
            "plans": plan_outputs,
        }
        print(json.dumps({"year": year, "contests": len(contest_map), "source_files": len(paths), "plans": len(plan_outputs)}, separators=(",", ":")))

    payload = {
        "schema": "ncsbe_all_plans_precinct_sort_benchmarks.v1",
        "plans": sorted(PLAN_TARGETS),
        "method": "Residential precinct-sort distributions reconciled by county/contest/party to official NCSBE totals; 2020 block VAP used for split precincts",
        "years": years,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    args.compare_output.write_text(json.dumps({"schema": "ncsbe_all_plans_precinct_sort_compare.v1", "benchmark": args.output.relative_to(ROOT).as_posix(), "rows": len(comparison_rows), "comparisons": comparison_rows}, indent=2) + "\n", encoding="utf-8")
    failed = any(plan["audit"]["unmatched_geographic_precincts"] or any(row["difference"] for row in plan["audit"]["statewide_totals"]) for item in years.values() for plan in item["plans"].values())
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
