#!/usr/bin/env python3
"""Measure congressional projection error against exact NCGA district totals.

This is an empirical sensitivity audit, not a claim that every estimated row has
the same error.  It compares the repository's precinct/VAP projection with rows
later replaced by exact NCGA StatPack totals and uses that observed distribution
as a practical reference for the remaining projected rows.  Early historical
reconstructions are reported separately because they use different source data.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "data/reports/ncsbe_all_plans_precinct_sort_benchmarks.json"
DEFAULT_HISTORICAL = ROOT / "data/reports/urban_sf1_historical/congressional_outlier_audit_2000_2004.json"
DEFAULT_OUTPUT = ROOT / "data/reports/congressional_uncertainty_audit.json"


def percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [abs(float(row["margin_error_pp"])) for row in rows]
    signed = [float(row["margin_error_pp"]) for row in rows]
    return {
        "rows": len(rows),
        "mean_signed_error_pp": round(sum(signed) / len(signed), 4) if signed else None,
        "mean_absolute_error_pp": round(sum(errors) / len(errors), 4) if errors else None,
        "median_absolute_error_pp": round(percentile(errors, 0.5), 4) if errors else None,
        "p90_absolute_error_pp": round(percentile(errors, 0.9), 4) if errors else None,
        "p95_absolute_error_pp": round(percentile(errors, 0.95), 4) if errors else None,
        "max_absolute_error_pp": round(max(errors), 4) if errors else None,
        "winner_disagreements": sum(bool(row["winner_disagreement"]) for row in rows),
    }


def is_exact(meta: dict[str, Any], district: str) -> bool:
    if meta.get("ncga_statpack_calibrated"):
        return True
    exact = {
        str(value)
        for key in ("targeted_ncga_statpack_districts", "ncga_shared_districts")
        for value in meta.get(key, [])
    }
    return str(district) in exact


def signed_margin(row: dict[str, Any]) -> float:
    if row.get("margin_pct") is not None:
        value = float(row["margin_pct"])
        winner = str(row.get("winner", "")).upper()
        return -abs(value) if winner == "DEM" else abs(value)
    total = float(row.get("total_votes") or 0)
    if total <= 0:
        return 0.0
    return 100.0 * (float(row.get("rep_votes") or 0) - float(row.get("dem_votes") or 0)) / total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--historical", type=Path, default=DEFAULT_HISTORICAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    calibration: list[dict[str, Any]] = []
    projected: list[dict[str, Any]] = []

    for year_text, year_payload in sorted(benchmark["years"].items()):
        for plan_name, plan in sorted(year_payload["plans"].items()):
            if plan.get("scope") != "congressional":
                continue
            live_dir = ROOT / plan["live_dir"]
            for contest, districts in sorted(plan["results"].items()):
                path = live_dir / f"congressional_{contest}.json"
                if not path.exists():
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                meta = payload.get("meta") or {}
                live = payload.get("general", {}).get("results", {})
                for district, projection in sorted(districts.items(), key=lambda item: int(item[0])):
                    official = live.get(district)
                    if not official:
                        continue
                    record = {
                        "year": int(year_text),
                        "plan": plan_name,
                        "contest": contest,
                        "district": district,
                        "file": path.relative_to(ROOT).as_posix(),
                    }
                    if is_exact(meta, district):
                        projected_margin = signed_margin(projection)
                        official_margin = signed_margin(official)
                        record.update({
                            "projected_margin_pct": round(projected_margin, 4),
                            "official_margin_pct": round(official_margin, 4),
                            "margin_error_pp": round(projected_margin - official_margin, 4),
                            "winner_disagreement": projection.get("winner") != official.get("winner"),
                        })
                        calibration.append(record)
                    else:
                        record.update({
                            "displayed_margin_pct": round(signed_margin(official), 4),
                            "match_coverage_pct": meta.get("match_coverage_pct"),
                        })
                        projected.append(record)

    overall = summarize(calibration)
    reference_p95 = float(overall["p95_absolute_error_pp"] or 0)
    for row in projected:
        margin = abs(float(row["displayed_margin_pct"]))
        row["sensitivity_band"] = "within_empirical_p95" if margin <= reference_p95 else "outside_empirical_p95"

    by_plan: dict[str, Any] = {}
    by_year: dict[str, Any] = {}
    for key, target in (("plan", by_plan), ("year", by_year)):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in calibration:
            groups[str(row[key])].append(row)
        target.update({name: summarize(items) for name, items in sorted(groups.items())})

    historical = json.loads(args.historical.read_text(encoding="utf-8"))
    historical_rows = historical.get("file_summaries", [])
    held = [row for row in historical_rows if not row.get("promotion_recommended")]
    historical_summary = {
        "comparison_files": len(historical_rows),
        "promotion_recommended_files": sum(bool(row.get("promotion_recommended")) for row in historical_rows),
        "held_files": len(held),
        "held_winner_flips": sum(int(row.get("winner_flips") or 0) for row in held),
        "held_max_absolute_margin_delta_pp": max((float(row.get("max_abs_margin_delta_pp") or 0) for row in held), default=0),
        "note": "Historical SF1/VTD reconstruction sensitivity is not pooled with the modern StatPack calibration distribution.",
        "held_details": held,
    }

    report = {
        "schema": "congressional_uncertainty_audit.v1",
        "method": "Compare precinct-sort/2020-block-VAP projections with exact NCGA StatPack district rows; signed margins are Republican minus Democratic percentage points.",
        "interpretation": "The empirical error distribution is a reference for similarly built modern projections, not a formal confidence interval or a guarantee for any individual contest.",
        "modern_calibration": {
            "overall": overall,
            "by_plan": by_plan,
            "by_year": by_year,
            "rows": calibration,
        },
        "remaining_modern_projections": {
            "rows": len(projected),
            "within_empirical_p95": sum(row["sensitivity_band"] == "within_empirical_p95" for row in projected),
            "outside_empirical_p95": sum(row["sensitivity_band"] == "outside_empirical_p95" for row in projected),
            "reference_p95_absolute_error_pp": reference_p95,
            "details": projected,
        },
        "historical_reconstruction": historical_summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": args.output.relative_to(ROOT).as_posix(),
        "modern_calibration": overall,
        "remaining_modern_projections": {
            key: report["remaining_modern_projections"][key]
            for key in ("rows", "within_empirical_p95", "outside_empirical_p95", "reference_p95_absolute_error_pp")
        },
        "historical_reconstruction": {
            key: historical_summary[key]
            for key in ("comparison_files", "promotion_recommended_files", "held_files", "held_winner_flips", "held_max_absolute_margin_delta_pp")
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
