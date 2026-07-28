#!/usr/bin/env python3
"""Rank district-level outliers in the 2002/2004 urban SF1 staging pilot.

The audit treats a production file as a usable comparison baseline only when
its statewide vote total is within two percent of the staged total. It also
attributes the staged votes coming from the historical urban linkages by
county and linkage strategy so large changes can be reviewed intelligently.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "data/reports/urban_sf1_historical"
LINKAGE_PATH = REPORT_DIR / "precinct_linkage.csv"
PILOT_DIRS = {
    2022: ROOT / "data/district_contests_urban_sf1_2022_lines",
    2024: ROOT / "data/district_contests_urban_sf1_2024_lines",
}
PRODUCTION_DIRS = {
    2022: ROOT / "data/district_contests",
    2024: ROOT / "data/district_contests_2024_lines",
}
RESULT_FILES = {
    2002: ROOT / "data/2002/20021105__nc__general__precinct.csv",
    2004: ROOT / "data/2004/20041102__nc__general__precinct.csv",
}
WEIGHT_FILES = {
    year: REPORT_DIR / f"district_weights_{year}.json" for year in (2002, 2004)
}
FILES = (
    "state_house_us_senate_2002.json",
    "state_senate_us_senate_2002.json",
    "state_house_president_2004.json",
    "state_senate_president_2004.json",
    "state_house_governor_2004.json",
    "state_senate_governor_2004.json",
)
OUT_CSV = REPORT_DIR / "district_outlier_audit_2002_2004.csv"
OUT_JSON = REPORT_DIR / "district_outlier_audit_2002_2004.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def result_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return ((payload.get("general") or {}).get("results") or {})


def statewide_total(payload: dict[str, Any]) -> float:
    return sum(number(row.get("total_votes")) for row in result_rows(payload).values())


def scope_name(line_year: int, chamber: str) -> str:
    if line_year == 2022:
        return f"2022_{chamber}_mqp"
    return f"2024_{chamber}"


def strategy_family(strategy: str) -> str:
    if strategy == "direct_sf1_vtd":
        return "direct_sf1_vtd"
    if strategy.startswith("historical_plan_cell_"):
        return "historical_plan_cell"
    if strategy.startswith("election_district_cell_"):
        return "election_district_cell"
    return strategy or "unknown"


def normalize_district(value: Any) -> str:
    text = str(value or "").strip()
    return str(int(text)) if text.isdigit() else text


def load_linkages() -> dict[int, list[dict[str, str]]]:
    output: dict[int, list[dict[str, str]]] = defaultdict(list)
    with LINKAGE_PATH.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            year = int(row["year"])
            if year in RESULT_FILES:
                output[year].append(row)
    return output


def raw_precinct_votes(year: int, office: str) -> dict[tuple[str, str], float]:
    totals: dict[tuple[str, str], float] = defaultdict(float)
    with RESULT_FILES[year].open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("office") or "").strip() != office:
                continue
            key = (
                str(row.get("county") or "").strip().upper(),
                str(row.get("precinct") or "").strip(),
            )
            totals[key] += number(row.get("votes"))
    return totals


def raw_office_total(year: int, office: str) -> float:
    return sum(raw_precinct_votes(year, office).values())


def linked_vote_attribution(
    *,
    year: int,
    office: str,
    scope: str,
    linkages: list[dict[str, str]],
    weights: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    raw_votes = raw_precinct_votes(year, office)
    precinct_weights = weights["scopes"][scope]["precincts"]
    district_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "votes": 0.0,
            "county_votes": defaultdict(float),
            "strategy_votes": defaultdict(float),
        }
    )
    for link in linkages:
        votes = raw_votes.get((link["county"].upper(), link["raw_precinct"]), 0.0)
        if votes <= 0:
            continue
        entries = precinct_weights.get(link["synthetic_key"]) or []
        for entry in entries:
            allocated = votes * number(entry.get("share"))
            district = normalize_district(entry.get("district"))
            if not district:
                continue
            data = district_data[district]
            data["votes"] += allocated
            data["county_votes"][link["county"]] += allocated
            data["strategy_votes"][strategy_family(link["strategy"])] += allocated
    return district_data


def top_parts(values: dict[str, float], total: float, limit: int = 4) -> str:
    if total <= 0:
        return ""
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return "; ".join(f"{name}:{value:.0f} ({100 * value / total:.1f}%)" for name, value in ordered)


def recommendation(
    *,
    baseline_usable: bool,
    candidate_complete: bool,
    candidate_margin: float,
    production_calibrated: bool,
    winner_flip: bool,
    margin_delta: float,
    district_vote_delta: float,
    production_district_total: float,
    plan_cell_share: float,
    linked_vote_share: float,
) -> tuple[str, str]:
    if not baseline_usable:
        if not candidate_complete:
            return (
                "candidate_failed_statewide_check",
                "Staged statewide total does not reconcile to the raw election result.",
            )
        if linked_vote_share >= 0.5 and (
            plan_cell_share >= 0.5 or abs(candidate_margin) <= 5
        ):
            return (
                "candidate_map_review",
                "Old production is incomplete; directly review this close or plan-cell-heavy urban candidate.",
            )
        return (
            "candidate_internal_checks_passed",
            "Old production is incomplete; staged statewide totals reconcile and no comparison is attempted.",
        )
    if production_calibrated:
        return (
            "production_calibration_review",
            "Production margin was manually calibrated; this is not a clean geometry comparison.",
        )
    if production_district_total <= 0:
        return (
            "inspect_missing_production_district",
            "Production has no votes for this district.",
        )
    district_delta_pct = 100 * abs(district_vote_delta) / production_district_total
    if linked_vote_share < 0.01 and (
        winner_flip or (district_delta_pct >= 25 and abs(district_vote_delta) >= 500)
    ):
        return (
            "fallback_allocation_review",
            "Large change occurs outside the linked urban vote; inspect fallback redistribution, not precinct geometry.",
        )
    if winner_flip:
        return ("map_inspection", "Winner changes relative to the complete production baseline.")
    if abs(margin_delta) >= 5:
        return ("map_inspection", "Margin changes by at least five percentage points.")
    if district_delta_pct >= 25 and abs(district_vote_delta) >= 500:
        return ("map_inspection", "District vote placement changes by at least 25 percent.")
    if abs(margin_delta) >= 2:
        return ("review", "Margin changes by two to five percentage points.")
    if plan_cell_share >= 0.5 and abs(margin_delta) >= 1:
        return (
            "review",
            "Most linked urban votes use a shared historical plan-cell allocation.",
        )
    return ("no_outlier_detected", "No material comparison outlier under the audit thresholds.")


def main() -> None:
    linkages = load_linkages()
    weights_by_year = {year: load_json(path) for year, path in WEIGHT_FILES.items()}
    rows: list[dict[str, Any]] = []
    file_summaries: list[dict[str, Any]] = []

    for line_year in (2022, 2024):
        for filename in FILES:
            pilot_path = PILOT_DIRS[line_year] / filename
            production_path = PRODUCTION_DIRS[line_year] / filename
            pilot = load_json(pilot_path)
            production = load_json(production_path)
            year = int(pilot["year"])
            office = str((pilot.get("meta") or {}).get("office") or "")
            chamber = str(pilot["scope"])
            scope = scope_name(line_year, chamber)
            pilot_total = statewide_total(pilot)
            production_total = statewide_total(production)
            raw_total = raw_office_total(year, office)
            candidate_raw_delta = pilot_total - raw_total
            candidate_complete = abs(candidate_raw_delta) <= max(25, raw_total * 0.0001)
            baseline_ratio = production_total / pilot_total if pilot_total else 0.0
            baseline_usable = 0.98 <= baseline_ratio <= 1.02
            attribution = linked_vote_attribution(
                year=year,
                office=office,
                scope=scope,
                linkages=linkages[year],
                weights=weights_by_year[year],
            )
            file_rows: list[dict[str, Any]] = []
            pilot_results = result_rows(pilot)
            production_results = result_rows(production)
            calibrated_districts = {
                normalize_district(value)
                for value in (production.get("meta") or {}).get(
                    "margin_calibration_target_districts", []
                )
            }
            districts = sorted(
                set(pilot_results) | set(production_results),
                key=lambda value: int(value) if value.isdigit() else value,
            )
            for district in districts:
                staged = pilot_results.get(district, {})
                prod = production_results.get(district, {})
                staged_total = number(staged.get("total_votes"))
                prod_total = number(prod.get("total_votes"))
                margin_delta = number(staged.get("margin_pct")) - number(prod.get("margin_pct"))
                vote_delta = staged_total - prod_total
                winner_flip = bool(
                    staged.get("winner")
                    and prod.get("winner")
                    and staged.get("winner") != prod.get("winner")
                )
                attr = attribution.get(
                    district,
                    {"votes": 0.0, "county_votes": {}, "strategy_votes": {}},
                )
                linked_votes = number(attr["votes"])
                strategy_votes = attr["strategy_votes"]
                plan_cell_votes = number(strategy_votes.get("historical_plan_cell"))
                plan_cell_share = plan_cell_votes / linked_votes if linked_votes else 0.0
                linked_vote_share = linked_votes / staged_total if staged_total else 0.0
                disposition, reason = recommendation(
                    baseline_usable=baseline_usable,
                    candidate_complete=candidate_complete,
                    candidate_margin=number(staged.get("margin_pct")),
                    production_calibrated=district in calibrated_districts,
                    winner_flip=winner_flip,
                    margin_delta=margin_delta,
                    district_vote_delta=vote_delta,
                    production_district_total=prod_total,
                    plan_cell_share=plan_cell_share,
                    linked_vote_share=linked_vote_share,
                )
                rank_score = (
                    abs(margin_delta)
                    + (20 if winner_flip else 0)
                    + min(20, 20 * abs(vote_delta) / prod_total) if prod_total else 100
                )
                row = {
                    "line_year": line_year,
                    "year": year,
                    "chamber": chamber,
                    "contest": pilot["contest_type"],
                    "file": filename,
                    "district": district,
                    "baseline_usable": baseline_usable,
                    "baseline_statewide_vote_ratio": round(baseline_ratio, 6),
                    "candidate_statewide_complete": candidate_complete,
                    "production_margin_pct": round(number(prod.get("margin_pct")), 4),
                    "staged_margin_pct": round(number(staged.get("margin_pct")), 4),
                    "staged_minus_production_pp": round(margin_delta, 4),
                    "production_winner": prod.get("winner", ""),
                    "staged_winner": staged.get("winner", ""),
                    "winner_flip": winner_flip,
                    "production_total_votes": int(round(prod_total)),
                    "staged_total_votes": int(round(staged_total)),
                    "staged_minus_production_votes": int(round(vote_delta)),
                    "linked_urban_votes": int(round(linked_votes)),
                    "linked_urban_share_of_staged_pct": round(
                        100 * linked_vote_share, 2
                    ),
                    "direct_vtd_linked_votes": int(
                        round(number(strategy_votes.get("direct_sf1_vtd")))
                    ),
                    "historical_plan_cell_linked_votes": int(round(plan_cell_votes)),
                    "historical_plan_cell_share_pct": round(100 * plan_cell_share, 2),
                    "top_linked_urban_counties": top_parts(
                        attr["county_votes"], linked_votes
                    ),
                    "linkage_method_mix": top_parts(strategy_votes, linked_votes),
                    "disposition": disposition,
                    "reason": reason,
                    "rank_score": round(rank_score, 4),
                }
                rows.append(row)
                file_rows.append(row)

            counts: dict[str, int] = defaultdict(int)
            for row in file_rows:
                counts[row["disposition"]] += 1
            comparable = [row for row in file_rows if row["baseline_usable"]]
            file_summaries.append(
                {
                    "line_year": line_year,
                    "file": filename,
                    "year": year,
                    "chamber": chamber,
                    "contest": pilot["contest_type"],
                    "pilot_statewide_votes": int(round(pilot_total)),
                    "raw_statewide_votes": int(round(raw_total)),
                    "pilot_minus_raw_votes": int(round(candidate_raw_delta)),
                    "candidate_statewide_complete": candidate_complete,
                    "production_statewide_votes": int(round(production_total)),
                    "production_to_pilot_vote_ratio": round(baseline_ratio, 6),
                    "baseline_usable": baseline_usable,
                    "disposition_counts": dict(sorted(counts.items())),
                    "winner_flips_on_usable_baseline": sum(
                        bool(row["winner_flip"]) for row in comparable
                    ),
                    "max_abs_margin_delta_on_usable_baseline": round(
                        max(
                            (
                                abs(number(row["staged_minus_production_pp"]))
                                for row in comparable
                            ),
                            default=0.0,
                        ),
                        4,
                    ),
                }
            )

    rows.sort(
        key=lambda row: (
            not bool(row["baseline_usable"]),
            -number(row["rank_score"]),
            int(row["line_year"]),
            row["file"],
            int(row["district"]) if str(row["district"]).isdigit() else 9999,
        )
    )
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    cross_contest_checks: list[dict[str, Any]] = []
    for line_year in (2022, 2024):
        for chamber in ("state_house", "state_senate"):
            president = result_rows(
                load_json(PILOT_DIRS[line_year] / f"{chamber}_president_2004.json")
            )
            governor = result_rows(
                load_json(PILOT_DIRS[line_year] / f"{chamber}_governor_2004.json")
            )
            deltas = []
            for district in set(president) | set(governor):
                pres_votes = number(president.get(district, {}).get("total_votes"))
                gov_votes = number(governor.get(district, {}).get("total_votes"))
                mean_votes = (pres_votes + gov_votes) / 2
                pct = 100 * abs(pres_votes - gov_votes) / mean_votes if mean_votes else 0.0
                deltas.append(
                    {
                        "district": district,
                        "president_votes": int(round(pres_votes)),
                        "governor_votes": int(round(gov_votes)),
                        "absolute_difference_pct": round(pct, 4),
                    }
                )
            deltas.sort(key=lambda row: -number(row["absolute_difference_pct"]))
            cross_contest_checks.append(
                {
                    "line_year": line_year,
                    "chamber": chamber,
                    "max_district_total_difference_pct": (
                        deltas[0]["absolute_difference_pct"] if deltas else 0.0
                    ),
                    "districts_over_5pct": sum(
                        number(row["absolute_difference_pct"]) > 5 for row in deltas
                    ),
                    "status": (
                        "pass"
                        if all(number(row["absolute_difference_pct"]) <= 5 for row in deltas)
                        else "review"
                    ),
                    "largest_differences": deltas[:5],
                }
            )

    usable_rows = [row for row in rows if row["baseline_usable"]]
    priority = [
        row
        for row in usable_rows
        if row["disposition"] in {"map_inspection", "inspect_missing_production_district"}
    ]
    candidate_review = [
        row for row in rows if row["disposition"] == "candidate_map_review"
    ]
    candidate_review.sort(
        key=lambda row: -(
            number(row["historical_plan_cell_share_pct"])
            + max(0.0, 10.0 - abs(number(row["staged_margin_pct"]))) * 5
            + number(row["linked_urban_share_of_staged_pct"]) / 10
        )
    )
    fallback_review = [
        row for row in usable_rows if row["disposition"] == "fallback_allocation_review"
    ]
    summary = {
        "schema": "urban_sf1_district_outlier_audit.v1",
        "production_modified": False,
        "years": [2002, 2004],
        "line_years": [2022, 2024],
        "baseline_rule": "Production statewide votes must be within 2% of staging.",
        "candidate_completeness_rule": "Staging must be within 25 votes or 0.01% of the raw office total.",
        "disposition_rules": {
            "map_inspection": "Winner flip, >=5pp margin delta, or >=25% district vote-placement delta with >=500 votes.",
            "review": "2-5pp margin delta, or >=1pp with at least half of linked urban votes allocated by historical plan cell.",
            "no_outlier_detected": "No material outlier under these thresholds.",
            "candidate_map_review": "Incomplete old baseline; directly review a candidate district dominated by linked urban plan-cell votes.",
            "candidate_internal_checks_passed": "Incomplete old baseline; staged statewide total reconciles to raw results.",
            "fallback_allocation_review": "Large change has no direct linked urban vote and belongs to the unmatched-vote fallback audit.",
            "production_calibration_review": "Production used a manual margin override and is not a clean geometry baseline.",
        },
        "file_summaries": file_summaries,
        "cross_contest_district_total_checks": cross_contest_checks,
        "usable_baseline_district_rows": len(usable_rows),
        "priority_map_inspection_rows": len(priority),
        "priority_map_inspection": priority[:40],
        "incomplete_baseline_candidate_review_rows": len(candidate_review),
        "incomplete_baseline_candidate_review": candidate_review[:40],
        "fallback_allocation_review_rows": len(fallback_review),
        "fallback_allocation_review": fallback_review[:40],
        "output_csv": str(OUT_CSV.relative_to(ROOT)).replace("\\", "/"),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
