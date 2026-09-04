#!/usr/bin/env python3
"""Build calibrated 2024 statewide results on the 2022 congressional plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_ncsbe2024_house_benchmarks as base  # noqa: E402


DEFAULT_SORT = ROOT / "downloads/ncsbe/2024_precinct_sort/STATEWIDE_PRECINCT_SORT.txt"
DEFAULT_OFFICIAL = ROOT / "data/2024/20241105__nc__general__precinct.csv"
DEFAULT_OUTPUT = ROOT / "data/reports/ncsbe2024_congressional_2022_lines_precinct_sort.json"
DEFAULT_COMPARE = ROOT / "data/reports/ncsbe2024_congressional_2022_lines_precinct_sort_compare.json"
LIVE_DIR = ROOT / "data/district_contests"


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct", "winner")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--precinct-sort", type=Path, default=DEFAULT_SORT)
    parser.add_argument("--official-results", type=Path, default=DEFAULT_OFFICIAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--compare-output", type=Path, default=DEFAULT_COMPARE)
    parser.add_argument("--chunksize", type=int, default=300_000)
    args = parser.parse_args()

    precinct_sort = base.load_precinct_sort(args.precinct_sort, args.chunksize)
    official = base.load_official_totals(args.official_results)
    reconciled, reconciliation = base.reconcile_to_official(precinct_sort, official)
    weights = base.load_plan_weights(
        ROOT / "data/tmp/block_assign_extract/NC_CD118.csv",
        assignment_block="GEOID",
        assignment_district="CDFP",
    )
    results, audit = base.project(reconciled, weights, official, district_count=14)

    benchmark = {
        "schema": "ncsbe2024_congressional_precinct_sort_benchmarks.v1",
        "source": base.SOURCE_URL,
        "official_totals_source": args.official_results.relative_to(ROOT).as_posix(),
        "plan": "2022 Interim Congressional (Court)",
        "plan_assignment": "data/tmp/block_assign_extract/NC_CD118.csv",
        "method": (
            "NCSBE 2024 residential precinct-sort distributions reconciled by county/contest/party "
            "to official totals, then allocated to official blocks with 2020 VAP weights"
        ),
        "privacy_note": "NCSBE precinct-sort noise is removed in aggregate by county/contest/party reconciliation.",
        "contests": sorted(base.CONTESTS.values()),
        "source_precinct_aliases": base.SOURCE_ALIASES,
        "reconciliation": reconciliation,
        "audit": audit,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8")

    comparisons: list[dict[str, Any]] = []
    missing_files: list[str] = []
    for contest, districts in sorted(results.items()):
        live_path = LIVE_DIR / f"congressional_{contest}.json"
        if not live_path.exists():
            missing_files.append(live_path.relative_to(ROOT).as_posix())
            continue
        live = json.loads(live_path.read_text(encoding="utf-8"))["general"]["results"]
        for district in sorted(districts, key=int):
            before = snapshot(live[district])
            after = snapshot(districts[district])
            comparisons.append(
                {
                    "file": live_path.relative_to(ROOT).as_posix(),
                    "contest": contest,
                    "district": district,
                    "current": before,
                    "calibrated_precinct_sort": after,
                    "delta": {
                        key: after[key] - before[key]
                        for key in ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct")
                    },
                }
            )

    compare = {
        "schema": "ncsbe2024_congressional_precinct_sort_compare.v1",
        "benchmark": args.output.relative_to(ROOT).as_posix(),
        "live_dir": LIVE_DIR.relative_to(ROOT).as_posix(),
        "rows": len(comparisons),
        "missing_files": missing_files,
        "comparisons": comparisons,
    }
    args.compare_output.write_text(json.dumps(compare, indent=2) + "\n", encoding="utf-8")

    cd13 = [row for row in comparisons if row["district"] == "13"]
    print(
        json.dumps(
            {
                "contests": len(results),
                "comparison_rows": len(comparisons),
                "missing_files": missing_files,
                "cd13": cd13,
                "audit": audit,
            },
            indent=2,
        )
    )
    failed = bool(missing_files) or bool(audit["unmatched_geographic_precincts"]) or any(
        row["difference"] for row in audit["statewide_totals"]
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
