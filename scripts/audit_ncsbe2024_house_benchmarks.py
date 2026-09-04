#!/usr/bin/env python3
"""Verify the reconciled 2024 State House slices against their benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANS = {
    "2022_lines": ROOT / "data" / "district_contests",
    "2024_lines": ROOT / "data" / "district_contests_2024_lines",
}
RESULT_FIELDS = (
    "dem_votes",
    "rep_votes",
    "other_votes",
    "total_votes",
    "margin",
    "margin_pct",
    "winner",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=ROOT / "data" / "reports" / "ncsbe2024_house_benchmarks_both_lines.json",
    )
    args = parser.parse_args()
    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))

    checked = 0
    for plan, live_dir in PLANS.items():
        contests = benchmark["plans"][plan]
        if len(contests) != 15:
            raise ValueError(f"{plan}: expected 15 contests, found {len(contests)}")
        audit = benchmark["audits"][plan]
        if audit["unmatched_geographic_precincts"]:
            raise ValueError(f"{plan}: unmatched geographic precincts remain")
        if any(row["difference"] != 0 for row in audit["statewide_totals"]):
            raise ValueError(f"{plan}: statewide totals do not reconcile")

        for contest, expected in contests.items():
            path = live_dir / f"state_house_{contest}.json"
            live = json.loads(path.read_text(encoding="utf-8"))["general"]["results"]
            if len(live) != 120 or len(expected) != 120:
                raise ValueError(
                    f"{plan}/{contest}: expected 120 districts; "
                    f"live={len(live)}, benchmark={len(expected)}"
                )
            for district, target in expected.items():
                row = live[district]
                if any(row.get(field) != target[field] for field in RESULT_FIELDS):
                    raise ValueError(f"{plan}/{contest}/HD-{district}: benchmark mismatch")
                if row["dem_votes"] + row["rep_votes"] + row["other_votes"] != row["total_votes"]:
                    raise ValueError(f"{plan}/{contest}/HD-{district}: total mismatch")
                if row["rep_votes"] - row["dem_votes"] != row["margin"]:
                    raise ValueError(f"{plan}/{contest}/HD-{district}: margin mismatch")
                expected_pct = round(100 * row["margin"] / row["total_votes"], 2) if row["total_votes"] else 0
                if row["margin_pct"] != expected_pct:
                    raise ValueError(f"{plan}/{contest}/HD-{district}: margin_pct mismatch")
                expected_winner = "REP" if row["margin"] > 0 else "DEM" if row["margin"] < 0 else "TIE"
                if row["winner"] != expected_winner:
                    raise ValueError(f"{plan}/{contest}/HD-{district}: winner mismatch")
                checked += 1

    print(json.dumps({"status": "ok", "validated_rows": checked, "expected_rows": 3600}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
