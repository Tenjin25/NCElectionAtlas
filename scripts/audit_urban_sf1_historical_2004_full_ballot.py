#!/usr/bin/env python3
"""Audit every staged 2004 statewide contest across modern district line sets."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RAW_RESULTS = ROOT / "data/2004/20041102__nc__general__precinct.csv"
REPORT_DIR = ROOT / "data/reports/urban_sf1_historical"
STAGING = {
    2022: ROOT / "data/district_contests_urban_sf1_2022_lines",
    2024: ROOT / "data/district_contests_urban_sf1_2024_lines",
}
PRODUCTION = {
    2022: ROOT / "data/district_contests",
    2024: ROOT / "data/district_contests_2024_lines",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def statewide_total(payload: dict) -> int:
    return sum(
        int(row.get("total_votes") or 0)
        for row in payload["general"]["results"].values()
    )


def raw_office_totals() -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    with RAW_RESULTS.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            totals[str(row.get("office") or "").strip()] += int(
                float(row.get("votes") or 0)
            )
    return dict(totals)


def geographic_sanity_checks() -> list[dict]:
    anchors = [
        (2022, "state_house", "98", "REP", "northern Mecklenburg"),
        (2022, "state_house", "102", "DEM", "central Charlotte"),
        (2022, "state_house", "103", "REP", "south Mecklenburg"),
        (2022, "state_house", "107", "DEM", "Charlotte core"),
        (2024, "state_house", "98", "REP", "northern Mecklenburg"),
        (2024, "state_house", "102", "DEM", "central Charlotte"),
        (2024, "state_house", "103", "REP", "south Mecklenburg"),
        (2024, "state_house", "107", "DEM", "Charlotte core"),
    ]
    checks = []
    for line_year, scope, district, expected, description in anchors:
        path = STAGING[line_year] / f"{scope}_president_2004.json"
        row = load(path)["general"]["results"][district]
        checks.append(
            {
                "line_year": line_year,
                "scope": scope,
                "district": district,
                "description": description,
                "expected_winner": expected,
                "actual_winner": row["winner"],
                "margin_pct": row["margin_pct"],
                "passed": row["winner"] == expected,
            }
        )
    return checks


def main() -> None:
    raw_totals = raw_office_totals()
    details: list[dict] = []
    summaries: list[dict] = []

    for line_year, staging_dir in STAGING.items():
        for staged_path in sorted(staging_dir.glob("*_2004.json")):
            staged = load(staged_path)
            scope = str(staged.get("scope") or "")
            if scope not in {"state_house", "state_senate", "congressional"}:
                continue

            office = str(staged.get("meta", {}).get("office") or "").strip()
            contest_type = str(staged.get("contest_type") or "")
            staged_results = staged["general"]["results"]
            raw_votes = int(raw_totals.get(office, 0))
            staged_votes = statewide_total(staged)
            production_path = PRODUCTION[line_year] / staged_path.name
            production = load(production_path) if production_path.exists() else None
            production_results = (
                production["general"]["results"] if production is not None else {}
            )

            max_delta = 0.0
            flips = 0
            for district, staged_row in sorted(
                staged_results.items(), key=lambda item: int(item[0])
            ):
                production_row = production_results.get(district)
                production_margin = (
                    float(production_row.get("margin_pct") or 0.0)
                    if production_row
                    else None
                )
                staged_margin = float(staged_row.get("margin_pct") or 0.0)
                margin_delta = (
                    round(staged_margin - production_margin, 2)
                    if production_margin is not None
                    else None
                )
                winner_flip = bool(
                    production_row
                    and production_row.get("winner") != staged_row.get("winner")
                )
                if margin_delta is not None:
                    max_delta = max(max_delta, abs(margin_delta))
                flips += int(winner_flip)
                details.append(
                    {
                        "line_year": line_year,
                        "scope": scope,
                        "contest_type": contest_type,
                        "file": staged_path.name,
                        "district": district,
                        "raw_statewide_votes": raw_votes,
                        "staged_statewide_votes": staged_votes,
                        "staged_minus_raw_votes": staged_votes - raw_votes,
                        "production_exists": production is not None,
                        "production_margin_pct": production_margin,
                        "staged_margin_pct": staged_margin,
                        "staged_minus_production_pp": margin_delta,
                        "production_winner": (
                            production_row.get("winner") if production_row else ""
                        ),
                        "staged_winner": staged_row.get("winner"),
                        "winner_flip": winner_flip,
                    }
                )

            complete = raw_votes > 0 and abs(staged_votes - raw_votes) <= max(
                20, len(staged_results)
            )
            summaries.append(
                {
                    "line_year": line_year,
                    "scope": scope,
                    "contest_type": contest_type,
                    "file": staged_path.name,
                    "districts": len(staged_results),
                    "raw_statewide_votes": raw_votes,
                    "staged_statewide_votes": staged_votes,
                    "staged_minus_raw_votes": staged_votes - raw_votes,
                    "candidate_complete": complete,
                    "production_exists": production is not None,
                    "winner_flips": flips if production else None,
                    "max_abs_margin_delta_pp": (
                        round(max_delta, 2) if production else None
                    ),
                    "disposition": (
                        "hold_geography_review" if complete else "reject_incomplete"
                    ),
                }
            )

    sanity_checks = geographic_sanity_checks()
    geography_passed = all(row["passed"] for row in sanity_checks)
    if geography_passed:
        for row in summaries:
            if row["candidate_complete"]:
                row["disposition"] = "promotion_candidate"

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    detail_path = REPORT_DIR / "full_ballot_2004_district_audit.csv"
    summary_path = REPORT_DIR / "full_ballot_2004_audit.json"
    with detail_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(details[0]))
        writer.writeheader()
        writer.writerows(details)

    dispositions: dict[str, int] = defaultdict(int)
    for row in summaries:
        dispositions[row["disposition"]] += 1
    payload = {
        "schema": "urban_sf1_historical_2004_full_ballot_audit.v1",
        "production_modified": False,
        "contest_count": len({row["contest_type"] for row in summaries}),
        "expected_files_by_line_set": {"2022": 51, "2024": 51},
        "file_summaries": summaries,
        "disposition_counts": dict(sorted(dispositions.items())),
        "geographic_sanity_passed": geography_passed,
        "geographic_sanity_checks": sanity_checks,
        "detail_csv": detail_path.relative_to(ROOT).as_posix(),
    }
    summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["disposition_counts"], indent=2))
    print(f"Wrote {len(summaries)} file summaries and {len(details)} district rows.")


if __name__ == "__main__":
    main()
