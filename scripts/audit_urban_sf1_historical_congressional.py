#!/usr/bin/env python3
"""Audit CD118/CD119 staging results using urban historical geography."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "data/reports/urban_sf1_historical"
STAGING = {
    2022: ROOT / "data/district_contests_urban_sf1_2022_lines",
    2024: ROOT / "data/district_contests_urban_sf1_2024_lines",
}
PRODUCTION = {
    2022: ROOT / "data/district_contests",
    2024: ROOT / "data/district_contests_2024_lines",
}
RAW = {
    2000: ROOT / "data/2000/20001107__nc__general__precinct.csv",
    2002: ROOT / "data/2002/20021105__nc__general__precinct.csv",
    2004: ROOT / "data/2004/20041102__nc__general__precinct.csv",
}
FILES = (
    "congressional_president_2000.json",
    "congressional_governor_2000.json",
    "congressional_us_senate_2002.json",
    "congressional_president_2004.json",
    "congressional_governor_2004.json",
    "congressional_us_senate_2004.json",
)
OUT_CSV = REPORT_DIR / "congressional_outlier_audit_2000_2004.csv"
OUT_JSON = REPORT_DIR / "congressional_outlier_audit_2000_2004.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return payload["general"]["results"]


def total(payload: dict[str, Any]) -> int:
    return sum(int(row["total_votes"]) for row in results(payload).values())


def raw_total(year: int, office: str) -> int:
    value = 0
    with RAW[year].open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("office") or "").strip() == office:
                value += int(float(row.get("votes") or 0))
    return value


def main() -> None:
    rows = []
    summaries = []
    for line_year in (2022, 2024):
        for filename in FILES:
            stage = load(STAGING[line_year] / filename)
            prod = load(PRODUCTION[line_year] / filename)
            year = int(stage["year"])
            office = str(stage["meta"]["office"])
            raw_votes = raw_total(year, office)
            stage_votes = total(stage)
            prod_votes = total(prod)
            stage_complete = abs(stage_votes - raw_votes) <= max(25, raw_votes * 0.0001)
            baseline_ratio = prod_votes / stage_votes if stage_votes else 0.0
            baseline_usable = 0.98 <= baseline_ratio <= 1.02
            file_rows = []
            for district in sorted(results(stage), key=int):
                staged = results(stage)[district]
                production = results(prod).get(district, {})
                delta = float(staged["margin_pct"]) - float(
                    production.get("margin_pct") or 0
                )
                flip = bool(
                    staged.get("winner")
                    and production.get("winner")
                    and staged["winner"] != production["winner"]
                )
                if not baseline_usable:
                    disposition = (
                        "candidate_complete"
                        if stage_complete
                        else "candidate_failed_statewide_total"
                    )
                elif flip or abs(delta) >= 5:
                    disposition = "map_review"
                elif abs(delta) >= 2:
                    disposition = "review"
                else:
                    disposition = "pass"
                row = {
                    "line_year": line_year,
                    "year": year,
                    "contest": stage["contest_type"],
                    "file": filename,
                    "district": district,
                    "raw_statewide_votes": raw_votes,
                    "staged_statewide_votes": stage_votes,
                    "staged_minus_raw_votes": stage_votes - raw_votes,
                    "candidate_complete": stage_complete,
                    "production_statewide_votes": prod_votes,
                    "baseline_usable": baseline_usable,
                    "production_margin_pct": production.get("margin_pct", ""),
                    "staged_margin_pct": staged["margin_pct"],
                    "staged_minus_production_pp": round(delta, 4),
                    "production_winner": production.get("winner", ""),
                    "staged_winner": staged["winner"],
                    "winner_flip": flip,
                    "production_total_votes": production.get("total_votes", 0),
                    "staged_total_votes": staged["total_votes"],
                    "disposition": disposition,
                }
                rows.append(row)
                file_rows.append(row)
            flips = sum(bool(row["winner_flip"]) for row in file_rows)
            max_delta = max(
                (abs(float(row["staged_minus_production_pp"])) for row in file_rows),
                default=0.0,
            )
            promotion_recommended = bool(
                stage_complete
                and year in {2002, 2004}
                and (
                    not baseline_usable
                    or (flips == 0 and max_delta < 2)
                )
            )
            summaries.append(
                {
                    "line_year": line_year,
                    "file": filename,
                    "year": year,
                    "contest": stage["contest_type"],
                    "districts": len(file_rows),
                    "raw_statewide_votes": raw_votes,
                    "staged_statewide_votes": stage_votes,
                    "staged_minus_raw_votes": stage_votes - raw_votes,
                    "candidate_complete": stage_complete,
                    "production_statewide_votes": prod_votes,
                    "production_to_staged_ratio": round(baseline_ratio, 6),
                    "baseline_usable": baseline_usable,
                    "winner_flips": flips,
                    "max_abs_margin_delta_pp": round(max_delta, 4),
                    "promotion_recommended": promotion_recommended,
                }
            )

    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "schema": "urban_sf1_historical_congressional_audit.v1",
        "production_modified": False,
        "promotion_rule": (
            "2002/2004 candidate reconciles to raw statewide total and either "
            "repairs an incomplete baseline or has no flips and <2pp maximum delta."
        ),
        "file_summaries": summaries,
        "promotion_files": [
            {"line_year": row["line_year"], "file": row["file"]}
            for row in summaries
            if row["promotion_recommended"]
        ],
        "held_2000_files": [
            {"line_year": row["line_year"], "file": row["file"]}
            for row in summaries
            if row["year"] == 2000
        ],
        "output_csv": str(OUT_CSV.relative_to(ROOT)).replace("\\", "/"),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
