#!/usr/bin/env python3
"""Audit or apply official NCGA StatPack rows to targeted House districts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from calibrate_district_slices_from_stats_csv import calculate_competitiveness


CONTEST_SLUGS = {
    "US President": "president",
    "US Senate": "us_senate",
    "NC Governor": "governor",
    "NC Lieutenant Governor": "lieutenant_governor",
    "NC Attorney General": "attorney_general",
    "NC Auditor": "auditor",
    "NC Commissioner of Agriculture": "agriculture_commissioner",
    "NC Commissioner of Insurance": "insurance_commissioner",
    "NC Commissioner of Labor": "labor_commissioner",
    "NC Secretary of State": "secretary_of_state",
    "NC Treasurer": "treasurer",
    # The misspelling is present in the official StatPack heading.
    "NC Superindendent of Public Instruction": "superintendent",
    "NC Supreme Court Associate Justice Seat 02": "nc_supreme_court_associate_justice_seat_02",
    "NC Supreme Court Associate Justice Seat 03": "nc_supreme_court_associate_justice_seat_03",
    "NC Supreme Court Associate Justice Seat 04": "nc_supreme_court_associate_justice_seat_04",
    "NC Supreme Court Associate Justice Seat 05": "nc_supreme_court_associate_justice_seat_05",
    "NC Supreme Court Chief Justice": "nc_supreme_court_chief_justice_seat_01",
}


def official_votes(party_values: dict[str, Any]) -> dict[str, int | float | str | dict[str, str]]:
    dem = int((party_values.get("Dem") or {}).get("votes") or 0)
    rep = int((party_values.get("Rep") or {}).get("votes") or 0)
    other = sum(
        int((values or {}).get("votes") or 0)
        for party, values in party_values.items()
        if party not in {"Dem", "Rep"}
    )
    total = dem + rep + other
    margin = rep - dem
    margin_pct = round((margin / total) * 100.0, 2) if total else 0.0
    winner = "REP" if margin > 0 else ("DEM" if margin < 0 else "TIE")
    return {
        "dem_votes": dem,
        "rep_votes": rep,
        "other_votes": other,
        "total_votes": total,
        "margin": margin,
        "margin_pct": margin_pct,
        "winner": winner,
        "competitiveness": {"color": calculate_competitiveness(margin_pct)},
    }


def row_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "dem_votes",
            "rep_votes",
            "other_votes",
            "total_votes",
            "margin",
            "margin_pct",
            "winner",
            "competitiveness",
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--live-dir", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    changes: list[dict[str, Any]] = []
    missing_files: list[str] = []
    unknown_contests: list[str] = []

    for contest in benchmark.get("contests", []):
        contest_name = str(contest.get("contest") or "")
        slug = CONTEST_SLUGS.get(contest_name)
        if not slug:
            unknown_contests.append(contest_name)
            continue
        year = int(contest.get("election_year") or 0)
        filename = f"state_house_{slug}_{year}.json"
        path = args.live_dir / filename
        if not path.exists():
            missing_files.append(str(path))
            continue

        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        results = ((payload.get("general") or {}).get("results") or {})
        file_changed = False

        for district, party_values in (contest.get("districts") or {}).items():
            row = results.get(district)
            if not isinstance(row, dict):
                changes.append(
                    {
                        "file": str(path),
                        "district": district,
                        "status": "missing_district",
                    }
                )
                continue
            before = row_snapshot(row)
            official = official_votes(party_values)
            after = {**before, **official}
            if before == after:
                continue
            changes.append(
                {
                    "file": str(path),
                    "district": district,
                    "election_year": year,
                    "contest": contest_name,
                    "source_pages": contest.get("source_pages"),
                    "before": before,
                    "after": after,
                }
            )
            if args.write:
                for key, value in official.items():
                    if key == "competitiveness" and isinstance(row.get(key), dict):
                        row[key]["color"] = value["color"]
                    else:
                        row[key] = value
                file_changed = True

        if args.write and file_changed:
            meta = payload.setdefault("meta", {})
            if isinstance(meta, dict):
                meta["targeted_ncga_statpack_districts"] = benchmark.get("target_districts", [])
                meta["targeted_ncga_statpack_source"] = benchmark.get("source_url")
                meta["targeted_ncga_statpack_plan"] = benchmark.get("plan_id")
            was_pretty = "\n" in raw_text.strip() and len(raw_text.strip().splitlines()) > 1
            output = (
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
                if was_pretty
                else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            )
            path.write_text(output, encoding="utf-8")

    report = {
        "mode": "write" if args.write else "audit",
        "benchmark": str(args.benchmark),
        "live_dir": str(args.live_dir),
        "plan_id": benchmark.get("plan_id"),
        "source_url": benchmark.get("source_url"),
        "changed_rows": len([item for item in changes if item.get("status") != "missing_district"]),
        "missing_files": sorted(set(missing_files)),
        "unknown_contests": sorted(set(unknown_contests)),
        "changes": changes,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("mode", "plan_id", "changed_rows", "missing_files", "unknown_contests")
            },
            indent=2,
        )
    )
    return 1 if missing_files or unknown_contests else 0


if __name__ == "__main__":
    raise SystemExit(main())
