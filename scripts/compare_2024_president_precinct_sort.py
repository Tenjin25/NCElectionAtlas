#!/usr/bin/env python3
"""Compare 2024 presidential projections with NCSBE precinct-sort results."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_ncsbe_mggg_senate_congress_benchmarks as benchmark  # noqa: E402


DEFAULT_SORT = ROOT / "downloads/ncsbe/2024_precinct_sort/STATEWIDE_PRECINCT_SORT.txt"
DEFAULT_LIVE = ROOT / "data/district_contests/congressional_president_2024.json"
DEFAULT_REPORT = ROOT / "data/reports/ncsbe2024_precinct_sort_congressional_president_compare.json"
SPLIT_KEYS = ("HARNETT - PR20", "WAKE - 10-05", "WAYNE - 23")


def load_president_precincts(path: Path) -> pd.DataFrame:
    columns = ["county", "contest_title", "precinct_code", "candidate_name", "candidate_party_lbl", "vote_ct"]
    pieces: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, sep="\t", dtype=str, usecols=columns, chunksize=250_000):
        selected = chunk[chunk["contest_title"].str.strip().str.upper() == "US PRESIDENT"].copy()
        if not selected.empty:
            pieces.append(selected)
    rows = pd.concat(pieces, ignore_index=True)
    rows["candidate_name"] = rows["candidate_name"].fillna("").str.strip().str.upper()
    rows = rows[~rows["candidate_name"].isin({"UNDER VOTE", "OVER VOTE"})].copy()
    rows["county"] = rows["county"].str.strip().str.upper()
    rows["precinct_code"] = rows["precinct_code"].str.strip().str.upper()
    rows["precinct_id"] = rows["county"] + " - " + rows["precinct_code"]
    rows["party"] = rows["candidate_party_lbl"].fillna("").str.strip().str.upper()
    rows["vote_ct"] = pd.to_numeric(rows["vote_ct"], errors="coerce").fillna(0)
    rows["vote_type"] = rows["party"].map(lambda p: "dem_votes" if p == "DEM" else ("rep_votes" if p == "REP" else "other_votes"))
    grouped = rows.groupby(["precinct_id", "vote_type"], as_index=False)["vote_ct"].sum()
    pivot = grouped.pivot(index="precinct_id", columns="vote_type", values="vote_ct").fillna(0).reset_index()
    for column in ("dem_votes", "rep_votes", "other_votes"):
        if column not in pivot:
            pivot[column] = 0
    return pivot[["precinct_id", "dem_votes", "rep_votes", "other_votes"]]


def result_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct", "winner")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--precinct-sort", type=Path, default=DEFAULT_SORT)
    parser.add_argument("--live", type=Path, default=DEFAULT_LIVE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    precinct = load_president_precincts(args.precinct_sort)
    crosswalk = benchmark.load_crosswalk(
        ROOT / "data/crosswalks/block20_to_sbe_2024.csv", "precinct_id", "block_geoid20"
    )
    vap = pd.read_csv(
        ROOT / "data/census/block_vap_2020_nc.csv", dtype={"block_geoid20": str}
    )[["block_geoid20", "vap_count"]]
    vap["block_geoid20"] = vap["block_geoid20"].astype(str).str.zfill(15)
    assignment = benchmark.load_assignment(benchmark.PLAN_SPECS["2022_congressional"])
    weights, county_weights = benchmark.build_weights(crosswalk, assignment, vap)
    projected, coverage = benchmark.project_precinct_votes(precinct, weights, county_weights)
    sorted_results = benchmark.result_rows(projected)

    live = json.loads(args.live.read_text(encoding="utf-8"))
    live_results = live["general"]["results"]
    comparisons: dict[str, Any] = {}
    for district in sorted(sorted_results, key=int):
        current = result_snapshot(live_results[district])
        sorted_row = result_snapshot(sorted_results[district])
        comparisons[district] = {
            "current": current,
            "precinct_sort": sorted_row,
            "delta_precinct_sort_minus_current": {
                key: sorted_row[key] - current[key]
                for key in ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct")
            },
        }

    split = weights[weights["precinct_id"].isin(SPLIT_KEYS)].merge(precinct, on="precinct_id", how="left")
    split_rows: list[dict[str, Any]] = []
    for row in split.to_dict("records"):
        split_rows.append(
            {
                "precinct_id": row["precinct_id"],
                "district": str(row["district"]),
                "vap_share": round(float(row["share"]), 8),
                "precinct_sort_votes": {
                    party: round(float(row[party]), 4)
                    for party in ("dem_votes", "rep_votes", "other_votes")
                },
                "allocated_votes": {
                    party: round(float(row[party]) * float(row["share"]), 4)
                    for party in ("dem_votes", "rep_votes", "other_votes")
                },
            }
        )

    report = {
        "schema": "ncsbe2024_precinct_sort_congressional_president_compare.v1",
        "precinct_sort_source": args.precinct_sort.relative_to(ROOT).as_posix(),
        "current_source": args.live.relative_to(ROOT).as_posix(),
        "plan": "2022 Interim Congressional (Court)",
        "method": "NCSBE residential precinct-sort totals allocated to plan with 2020 block VAP; unmatched precincts allocated by county VAP",
        "privacy_note": "NCSBE adds statistical noise to precinct-sort results; these are analytical, not official reporting totals.",
        "coverage": coverage,
        "district_comparisons": comparisons,
        "split_precincts_touching_district_13": split_rows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"district_13": comparisons["13"], "coverage": coverage}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
