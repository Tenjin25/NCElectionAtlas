#!/usr/bin/env python3
"""Compare production, alias-only, and Census-2000-VAP Mecklenburg pilots."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "data/reports/mecklenburg_vap2000_legislative_pilot_compare.csv"
OUT_JSON = ROOT / "data/reports/mecklenburg_vap2000_legislative_pilot_summary.json"
LINEAGE_JSON = ROOT / "data/reports/mecklenburg_2000_precinct_lineage_audit_summary.json"
CELL_VALIDATION_JSON = (
    ROOT / "data/reports/mecklenburg_sf1_district_cell_pilot_validation.json"
)

CONFIGS = (
    {
        "line_year": 2022,
        "production": ROOT / "data/district_contests",
        "alias": ROOT / "data/district_contests_mecklenburg_alias_experiment_2000_2002",
        "vap": ROOT / "data/district_contests_mecklenburg_vap2000_2022_lines",
    },
    {
        "line_year": 2024,
        "production": ROOT / "data/district_contests_2024_lines",
        "alias": ROOT / "data/district_contests_mecklenburg_alias_2024_lines",
        "vap": ROOT / "data/district_contests_mecklenburg_vap2000_2024_lines",
    },
)

FILES = (
    "state_house_president_2000.json",
    "state_senate_president_2000.json",
    "state_house_governor_2000.json",
    "state_senate_governor_2000.json",
)
MATERIAL_MARGIN_DELTA_PP = 0.05


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def result_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return (payload.get("general") or {}).get("results") or {}


def num(result: dict[str, Any], key: str) -> float:
    try:
        return float(result.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def total_votes(results: dict[str, dict[str, Any]]) -> int:
    return sum(int(round(num(result, "total_votes"))) for result in results.values())


def main() -> None:
    rows: list[dict[str, Any]] = []
    conservation: list[dict[str, Any]] = []
    parse_errors: list[str] = []

    for config in CONFIGS:
        for filename in FILES:
            try:
                payloads = {
                    key: load(config[key] / filename)
                    for key in ("production", "alias", "vap")
                }
            except Exception as exc:
                parse_errors.append(f"{config['line_year']} {filename}: {exc}")
                continue
            results = {key: result_map(value) for key, value in payloads.items()}
            totals = {key: total_votes(value) for key, value in results.items()}
            conservation.append(
                {
                    "line_year": config["line_year"],
                    "file": filename,
                    **{f"{key}_district_total_votes": value for key, value in totals.items()},
                    "vap_minus_alias_total_votes": totals["vap"] - totals["alias"],
                }
            )

            districts = sorted(
                set(results["production"]) | set(results["alias"]) | set(results["vap"]),
                key=lambda value: (not str(value).isdigit(), int(value) if str(value).isdigit() else str(value)),
            )
            for district in districts:
                prod = results["production"].get(district, {})
                alias = results["alias"].get(district, {})
                vap = results["vap"].get(district, {})
                prod_pct = num(prod, "margin_pct")
                alias_pct = num(alias, "margin_pct")
                vap_pct = num(vap, "margin_pct")
                alias_delta = alias_pct - prod_pct
                vap_delta = vap_pct - alias_pct
                combined_delta = vap_pct - prod_pct
                if max(abs(alias_delta), abs(vap_delta), abs(combined_delta)) < 0.005:
                    continue
                rows.append(
                    {
                        "line_year": config["line_year"],
                        "file": filename,
                        "scope": payloads["vap"].get("scope", ""),
                        "contest_type": payloads["vap"].get("contest_type", ""),
                        "district": district,
                        "production_margin_pct": round(prod_pct, 4),
                        "alias_margin_pct": round(alias_pct, 4),
                        "vap2000_fractional_margin_pct": round(vap_pct, 4),
                        "alias_minus_production_pp": round(alias_delta, 4),
                        "vap2000_minus_alias_pp": round(vap_delta, 4),
                        "vap2000_minus_production_pp": round(combined_delta, 4),
                        "production_winner": prod.get("winner", ""),
                        "alias_winner": alias.get("winner", ""),
                        "vap2000_winner": vap.get("winner", ""),
                        "vap2000_winner_flip_vs_alias": bool(
                            alias.get("winner") and vap.get("winner") and alias.get("winner") != vap.get("winner")
                        ),
                        "vap2000_winner_flip_vs_production": bool(
                            prod.get("winner") and vap.get("winner") and prod.get("winner") != vap.get("winner")
                        ),
                    }
                )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["line_year", "file"]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    by_year: dict[str, Any] = {}
    for year in (2022, 2024):
        subset = [row for row in rows if row["line_year"] == year]
        vap_effect = [
            row
            for row in subset
            if abs(float(row["vap2000_minus_alias_pp"])) >= MATERIAL_MARGIN_DELTA_PP
        ]
        by_year[str(year)] = {
            "pipeline_comparison_rows": len(subset),
            "material_margin_delta_threshold_pp": MATERIAL_MARGIN_DELTA_PP,
            "vap2000_effect_rows": len(vap_effect),
            "vap2000_effect_districts": sorted(
                {str(row["district"]) for row in vap_effect},
                key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value),
            ),
            "max_abs_alias_minus_production_pp": max(
                (abs(float(row["alias_minus_production_pp"])) for row in subset), default=0
            ),
            "max_abs_vap2000_minus_alias_pp": max(
                (abs(float(row["vap2000_minus_alias_pp"])) for row in vap_effect), default=0
            ),
            "mean_abs_vap2000_minus_alias_pp": round(
                sum(abs(float(row["vap2000_minus_alias_pp"])) for row in vap_effect)
                / len(vap_effect)
                if vap_effect
                else 0.0,
                6,
            ),
            "max_abs_vap2000_minus_production_pp": max(
                (abs(float(row["vap2000_minus_production_pp"])) for row in subset), default=0
            ),
            "vap2000_winner_flips_vs_alias": [
                {
                    "file": row["file"],
                    "district": row["district"],
                    "alias_winner": row["alias_winner"],
                    "vap2000_winner": row["vap2000_winner"],
                }
                for row in subset
                if row["vap2000_winner_flip_vs_alias"]
            ],
            "vap2000_winner_flips_vs_production": [
                {
                    "file": row["file"],
                    "district": row["district"],
                    "production_winner": row["production_winner"],
                    "vap2000_winner": row["vap2000_winner"],
                }
                for row in subset
                if row["vap2000_winner_flip_vs_production"]
            ],
        }

    lineage = load(LINEAGE_JSON) if LINEAGE_JSON.exists() else {}
    cell_validation = load(CELL_VALIDATION_JSON) if CELL_VALIDATION_JSON.exists() else {}
    summary = {
        "schema": "mecklenburg_vap2000_legislative_pilot.v1",
        "production_modified": False,
        "production_safe": False,
        "production_safe_reasons": [
            (
                "Direct numeric joins from 2000 election precincts to later VTD/SBE "
                "codes are invalid and are not used by the revised pilot."
            ),
            (
                "The revised House/Senate/CD cell method passes the known HD98 "
                "geography check but is still coarse within each 2000 district cell."
            ),
        ],
        "method": "2000 election House/Senate/CD cell + Census 2000 SF1 P005001 VAP + fractional NHGIS 2000->2010->2020 block flow",
        "comparison_rows": len(rows),
        "parse_errors": parse_errors,
        "vote_conservation": conservation,
        "vote_conservation_exact": all(
            int(row["vap_minus_alias_total_votes"]) == 0 for row in conservation
        ),
        "max_abs_rounding_delta_votes": max(
            (abs(int(row["vap_minus_alias_total_votes"])) for row in conservation), default=0
        ),
        "vote_conservation_within_rounding": all(
            abs(int(row["vap_minus_alias_total_votes"])) <= 10 for row in conservation
        ),
        "by_line_year": by_year,
        "lineage_audit": {
            "summary_json": str(LINEAGE_JSON.relative_to(ROOT)).replace("\\", "/"),
            "loaded": bool(lineage),
            "direct_same_code_bridge_rejected": True,
            "quarantined_precinct_codes": lineage.get("quarantined_precinct_codes"),
        },
        "district_cell_validation": {
            "summary_json": str(CELL_VALIDATION_JSON.relative_to(ROOT)).replace("\\", "/"),
            "loaded": bool(cell_validation),
            "cell_join_complete": cell_validation.get("cell_join_complete"),
            "hd98_geography_sanity_passed": cell_validation.get(
                "hd98_geography_sanity_passed"
            ),
            "hd98_2024_charlotte_share_pct": cell_validation.get(
                "hd98_2024_charlotte_share_pct"
            ),
            "hd98_2024_president": cell_validation.get("hd98_2024_president", {}),
        },
        "comparison_csv": str(OUT_CSV.relative_to(ROOT)).replace("\\", "/"),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
