#!/usr/bin/env python3
"""Audit statewide staging results from the urban SF1 historical pilot."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PILOT_DIRS = {
    2022: ROOT / "data/district_contests_urban_sf1_2022_lines",
    2024: ROOT / "data/district_contests_urban_sf1_2024_lines",
}
PRODUCTION_DIRS = {
    2022: ROOT / "data/district_contests",
    2024: ROOT / "data/district_contests_2024_lines",
}
FILES = (
    "state_house_president_2000.json",
    "state_senate_president_2000.json",
    "state_house_governor_2000.json",
    "state_senate_governor_2000.json",
    "state_house_us_senate_2002.json",
    "state_senate_us_senate_2002.json",
    "state_house_president_2004.json",
    "state_senate_president_2004.json",
    "state_house_governor_2004.json",
    "state_senate_governor_2004.json",
)
RESULT_FILES = {
    2000: ROOT / "data/2000/20001107__nc__general__precinct.csv",
    2002: ROOT / "data/2002/20021105__nc__general__precinct.csv",
    2004: ROOT / "data/2004/20041102__nc__general__precinct.csv",
}
LINKAGE = ROOT / "data/reports/urban_sf1_historical/precinct_linkage.csv"
WEIGHTS = {
    year: ROOT / f"data/reports/urban_sf1_historical/district_weights_{year}.json"
    for year in (2000, 2002, 2004)
}
OUT_CSV = ROOT / "data/reports/urban_sf1_historical/result_comparison.csv"
OUT_JSON = ROOT / "data/reports/urban_sf1_historical/validation.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return ((payload.get("general") or {}).get("results") or {})


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def district_total(payload: dict[str, Any]) -> int:
    return sum(int(round(number(row.get("total_votes")))) for row in results(payload).values())


def raw_office_total(year: int, office: str) -> int:
    total = 0
    with RESULT_FILES[year].open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("office") or "").strip() != office:
                continue
            try:
                total += int(float(row.get("votes") or 0))
            except ValueError:
                pass
    return total


def main() -> None:
    rows: list[dict[str, Any]] = []
    file_checks: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    for line_year in (2022, 2024):
        for filename in FILES:
            pilot_path = PILOT_DIRS[line_year] / filename
            production_path = PRODUCTION_DIRS[line_year] / filename
            if not pilot_path.exists() or not production_path.exists():
                parse_errors.append(f"missing {line_year} {filename}")
                continue
            pilot = load(pilot_path)
            production = load(production_path)
            year = int(pilot.get("year") or 0)
            office = str((pilot.get("meta") or {}).get("office") or "")
            raw_total = raw_office_total(year, office)
            p_total = district_total(pilot)
            prod_total = district_total(production)
            file_checks.append(
                {
                    "line_year": line_year,
                    "file": filename,
                    "year": year,
                    "office": office,
                    "raw_office_votes": raw_total,
                    "pilot_district_votes": p_total,
                    "pilot_minus_raw_votes": p_total - raw_total,
                    "production_district_votes": prod_total,
                    "pilot_minus_production_votes": p_total - prod_total,
                    "pilot_match_coverage_pct": (pilot.get("meta") or {}).get(
                        "match_coverage_pct"
                    ),
                    "production_match_coverage_pct": (
                        production.get("meta") or {}
                    ).get("match_coverage_pct"),
                }
            )
            pilot_results = results(pilot)
            production_results = results(production)
            for district in sorted(
                set(pilot_results) | set(production_results),
                key=lambda value: int(value) if str(value).isdigit() else str(value),
            ):
                p = pilot_results.get(district, {})
                prod = production_results.get(district, {})
                delta = number(p.get("margin_pct")) - number(prod.get("margin_pct"))
                if abs(delta) < 0.005:
                    continue
                rows.append(
                    {
                        "line_year": line_year,
                        "file": filename,
                        "year": year,
                        "scope": pilot.get("scope"),
                        "contest_type": pilot.get("contest_type"),
                        "district": district,
                        "production_margin_pct": round(
                            number(prod.get("margin_pct")), 4
                        ),
                        "pilot_margin_pct": round(number(p.get("margin_pct")), 4),
                        "pilot_minus_production_pp": round(delta, 4),
                        "production_winner": prod.get("winner", ""),
                        "pilot_winner": p.get("winner", ""),
                        "winner_flip": bool(
                            prod.get("winner")
                            and p.get("winner")
                            and prod.get("winner") != p.get("winner")
                        ),
                        "production_total_votes": int(
                            round(number(prod.get("total_votes")))
                        ),
                        "pilot_total_votes": int(round(number(p.get("total_votes")))),
                    }
                )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=list(rows[0]) if rows else ["line_year", "file"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    linkage_rows = list(csv.DictReader(LINKAGE.open(newline="", encoding="utf-8-sig")))
    strategy_counts: dict[str, int] = {}
    for row in linkage_rows:
        strategy = row.get("strategy") or ""
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

    max_share_error = 0.0
    missing_weight_keys: list[str] = []
    scopes = (
        "2022_state_house_mqp",
        "2022_state_senate_mqp",
        "2022_congressional_cd118",
        "2024_state_house",
        "2024_state_senate",
        "2024_congressional_cd119",
    )
    for year in (2000, 2002, 2004):
        payload = load(WEIGHTS[year])
        keys = {
            row["synthetic_key"]
            for row in linkage_rows
            if int(row["year"]) == year
        }
        for scope in scopes:
            precincts = payload["scopes"][scope]["precincts"]
            for key in keys:
                entries = precincts.get(key)
                if not entries:
                    missing_weight_keys.append(f"{year} {scope} {key}")
                    continue
                max_share_error = max(
                    max_share_error,
                    abs(sum(number(item.get("share")) for item in entries) - 1.0),
                )

    material = [row for row in rows if abs(number(row["pilot_minus_production_pp"])) >= 1.0]
    summary = {
        "schema": "urban_sf1_historical_legislative_pilot_validation.v1",
        "production_modified": False,
        "parse_errors": parse_errors,
        "linkage_precincts": len(linkage_rows),
        "linkage_strategy_counts": strategy_counts,
        "missing_weight_keys": missing_weight_keys,
        "max_abs_weight_share_sum_error": max_share_error,
        "file_vote_checks": file_checks,
        "comparison_rows": len(rows),
        "material_delta_threshold_pp": 1.0,
        "material_delta_rows": len(material),
        "max_abs_margin_delta_pp": max(
            (abs(number(row["pilot_minus_production_pp"])) for row in rows), default=0
        ),
        "winner_flips": [
            {
                "line_year": row["line_year"],
                "file": row["file"],
                "district": row["district"],
                "production_winner": row["production_winner"],
                "pilot_winner": row["pilot_winner"],
            }
            for row in rows
            if row["winner_flip"]
        ],
        "known_mecklenburg_hd98_check": {
            "2024_lines_2000_president": next(
                (
                    {
                        "margin_pct": row["pilot_margin_pct"],
                        "winner": row["pilot_winner"],
                        "total_votes": row["pilot_total_votes"],
                    }
                    for row in rows
                    if row["line_year"] == 2024
                    and row["file"] == "state_house_president_2000.json"
                    and str(row["district"]) == "98"
                ),
                {},
            )
        },
        "production_safe": False,
        "production_safe_reason": (
            "Staging comparison only; large district changes and direct-VTD "
            "rejections require county-level review before promotion."
        ),
        "comparison_csv": str(OUT_CSV.relative_to(ROOT)).replace("\\", "/"),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
