#!/usr/bin/env python3
"""Audit or apply official NCGA StatPack election totals to district slices."""

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
    # This spelling appears in the NCGA source PDFs.
    "NC Superindendent of Public Instruction": "superintendent",
    "NC Supreme Court Associate Justice Seat 02": "nc_supreme_court_associate_justice_seat_02",
    "NC Supreme Court Associate Justice Seat 03": "nc_supreme_court_associate_justice_seat_03",
    "NC Supreme Court Associate Justice Seat 04": "nc_supreme_court_associate_justice_seat_04",
    "NC Supreme Court Associate Justice Seat 05": "nc_supreme_court_associate_justice_seat_05",
    "NC Supreme Court Associate Justice Seat 06": "nc_supreme_court_associate_justice_seat_06",
    "NC Supreme Court Chief Justice": "nc_supreme_court_chief_justice_seat_01",
}


def official_values(parties: dict[str, Any]) -> dict[str, Any]:
    dem = int((parties.get("Dem") or {}).get("votes") or 0)
    rep = int((parties.get("Rep") or {}).get("votes") or 0)
    other = sum(
        int((values or {}).get("votes") or 0)
        for party, values in parties.items()
        if party not in {"Dem", "Rep"}
    )
    total = dem + rep + other
    margin = rep - dem
    margin_pct = round(100.0 * margin / total, 2) if total else 0.0
    return {
        "dem_votes": dem,
        "rep_votes": rep,
        "other_votes": other,
        "total_votes": total,
        "margin": margin,
        "margin_pct": margin_pct,
        "winner": "REP" if margin > 0 else ("DEM" if margin < 0 else "TIE"),
        "competitiveness": {"color": calculate_competitiveness(margin_pct)},
    }


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    keys = ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct", "winner", "competitiveness")
    return {key: row.get(key) for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--live-dir", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    scope = str(benchmark.get("scope") or "")
    changes: list[dict[str, Any]] = []
    missing_files: list[str] = []
    missing_districts: list[dict[str, str]] = []
    unknown_contests: set[str] = set()

    for contest in benchmark.get("contests", []):
        name = str(contest.get("contest") or "")
        slug = CONTEST_SLUGS.get(name)
        if slug is None:
            unknown_contests.add(name)
            continue
        year = int(contest.get("election_year") or 0)
        path = args.live_dir / f"{scope}_{slug}_{year}.json"
        if not path.exists():
            missing_files.append(str(path))
            continue
        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        results = ((payload.get("general") or {}).get("results") or {})
        changed = False
        for district, party_values in (contest.get("districts") or {}).items():
            row = results.get(district)
            if not isinstance(row, dict):
                missing_districts.append({"file": str(path), "district": district})
                continue
            before = snapshot(row)
            after = official_values(party_values)
            if before == after:
                continue
            changes.append({
                "file": str(path),
                "district": district,
                "election_year": year,
                "contest": name,
                "source_pages": contest.get("source_pages"),
                "before": before,
                "after": after,
                "margin_pct_delta": round(after["margin_pct"] - float(before.get("margin_pct") or 0), 2),
            })
            if args.write:
                row.update(after)
                changed = True
        if args.write and changed:
            meta = payload.setdefault("meta", {})
            meta["ncga_statpack_source"] = benchmark.get("source_url")
            meta["ncga_statpack_plan"] = benchmark.get("plan_id")
            meta["ncga_statpack_calibrated"] = True
            output = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            path.write_text(output, encoding="utf-8")

    report = {
        "mode": "write" if args.write else "audit",
        "benchmark": str(args.benchmark),
        "live_dir": str(args.live_dir),
        "scope": scope,
        "plan_id": benchmark.get("plan_id"),
        "source_url": benchmark.get("source_url"),
        "changed_rows": len(changes),
        "missing_files": sorted(set(missing_files)),
        "missing_districts": missing_districts,
        "unknown_contests": sorted(unknown_contests),
        "changes": changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "mode", "scope", "plan_id", "changed_rows", "missing_files", "missing_districts", "unknown_contests"
    )}, indent=2))
    return 1 if missing_files or missing_districts or unknown_contests else 0


if __name__ == "__main__":
    raise SystemExit(main())
