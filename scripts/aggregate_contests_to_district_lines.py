#!/usr/bin/env python3
"""Aggregate precinct contest slices onto configured district line sets.

This lightweight path consumes data/contests/*.json plus the checked-in modern
precinct-to-district crosswalks. It is intended for recent elections whose
precinct identifiers use the same modern basis as those crosswalks.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINE_SETS = {
    "2022": {
        "out_dir": ROOT / "data/district_contests",
        "label": "2022 lines",
        "crosswalks": {
            "congressional": ROOT / "data/crosswalks/precinct_to_cd118.csv",
            "state_house": ROOT / "data/crosswalks/precinct_to_2022_state_house.csv",
            "state_senate": ROOT / "data/crosswalks/precinct_to_2022_state_senate.csv",
        },
    },
    "2024": {
        "out_dir": ROOT / "data/district_contests_2024_lines",
        "label": "2024 lines",
        "crosswalks": {
            "congressional": ROOT / "data/crosswalks/precinct_to_cd119.csv",
            "state_house": ROOT / "data/crosswalks/precinct_to_2024_state_house.csv",
            "state_senate": ROOT / "data/crosswalks/precinct_to_2024_state_senate.csv",
        },
    },
    "2026": {
        "out_dir": ROOT / "data/district_contests_2026_lines",
        "label": "2026 congressional lines",
        "crosswalks": {
            "congressional": ROOT / "data/crosswalks/precinct_to_cd2026_sl2025_95.csv",
        },
    },
}


def calculate_competitiveness(margin_pct: float) -> str:
    absolute = abs(margin_pct)
    if absolute < 0.5:
        return "#f7f7f7"
    republican = margin_pct > 0
    thresholds = (
        (40, "#67000d", "#08306b"),
        (30, "#a50f15", "#08519c"),
        (20, "#cb181d", "#3182bd"),
        (10, "#ef3b2c", "#6baed6"),
        (5.5, "#fb6a4a", "#9ecae1"),
        (1, "#fcae91", "#c6dbef"),
    )
    for threshold, rep_color, dem_color in thresholds:
        if absolute >= threshold:
            return rep_color if republican else dem_color
    return "#fee8c8" if republican else "#e1f5fe"


def normalize_precinct(value: object) -> str:
    return " ".join(str(value or "").strip().upper().split())


def load_crosswalk(path: Path) -> tuple[dict[str, list[tuple[str, float]]], dict[str, list[tuple[str, float]]]]:
    by_precinct: dict[str, list[tuple[str, float]]] = defaultdict(list)
    county_district_mass: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            precinct = normalize_precinct(row.get("precinct_key"))
            district = str(row.get("district_num") or row.get("district") or "").strip().lstrip("0") or "0"
            if not precinct or not district:
                continue
            try:
                weight = float(row.get("area_weight") or 0)
            except ValueError:
                continue
            if weight <= 0:
                continue
            by_precinct[precinct].append((district, weight))
            county = precinct.split(" - ", 1)[0]
            try:
                mass = float(row.get("vap_count") or 0)
            except ValueError:
                mass = 0.0
            county_district_mass[county][district] += mass if mass > 0 else weight

    county_fallback: dict[str, list[tuple[str, float]]] = {}
    for county, values in county_district_mass.items():
        total = sum(values.values())
        if total > 0:
            county_fallback[county] = [(district, value / total) for district, value in values.items()]
    return dict(by_precinct), county_fallback


def apportion(values: dict[str, float], target: int) -> dict[str, int]:
    floors = {key: math.floor(max(0.0, value)) for key, value in values.items()}
    remaining = int(target) - sum(floors.values())
    if remaining > 0:
        order = sorted(values, key=lambda key: (values[key] - floors[key], key), reverse=True)
        for key in order[:remaining]:
            floors[key] += 1
    elif remaining < 0:
        order = sorted(values, key=lambda key: (values[key] - floors[key], key))
        for key in order[: abs(remaining)]:
            if floors[key] > 0:
                floors[key] -= 1
    return floors


def aggregate_contest(payload: dict, crosswalk_path: Path) -> tuple[dict, dict]:
    by_precinct, county_fallback = load_crosswalk(crosswalk_path)
    floating: dict[str, dict[str, float]] = defaultdict(
        lambda: {"dem_votes": 0.0, "rep_votes": 0.0, "other_votes": 0.0}
    )
    source_totals = {"dem_votes": 0, "rep_votes": 0, "other_votes": 0}
    matched = 0
    fallback = 0
    rows = payload.get("rows") or []
    for row in rows:
        precinct = normalize_precinct(row.get("county"))
        county = precinct.split(" - ", 1)[0]
        allocation = by_precinct.get(precinct)
        if not allocation:
            allocation = county_fallback.get(county)
            fallback += 1 if allocation else 0
        if not allocation:
            continue
        matched += 1
        weight_total = sum(weight for _, weight in allocation)
        if weight_total <= 0:
            continue
        for bucket in source_totals:
            votes = int(row.get(bucket, 0) or 0)
            source_totals[bucket] += votes
            for district, weight in allocation:
                floating[district][bucket] += votes * weight / weight_total

    apportioned = {
        bucket: apportion(
            {district: values[bucket] for district, values in floating.items()},
            source_totals[bucket],
        )
        for bucket in source_totals
    }
    dem_candidate = next((str(row.get("dem_candidate") or "") for row in rows if row.get("dem_candidate")), "")
    rep_candidate = next((str(row.get("rep_candidate") or "") for row in rows if row.get("rep_candidate")), "")
    results = {}
    for district in sorted(floating, key=lambda value: (int(value) if value.isdigit() else 10**9, value)):
        dem = apportioned["dem_votes"].get(district, 0)
        rep = apportioned["rep_votes"].get(district, 0)
        other = apportioned["other_votes"].get(district, 0)
        total = dem + rep + other
        margin = rep - dem
        margin_pct = margin / total * 100 if total else 0.0
        results[district] = {
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": other,
            "total_votes": total,
            "dem_candidate": dem_candidate,
            "rep_candidate": rep_candidate,
            "margin": margin,
            "margin_pct": round(margin_pct, 2),
            "winner": "REP" if margin > 0 else "DEM" if margin < 0 else "TIE",
            "competitiveness": {"color": calculate_competitiveness(margin_pct)},
        }
    diagnostics = {
        "matched_precinct_keys": matched,
        "total_precinct_keys": len(rows),
        "county_fallback_precinct_keys": fallback,
        "match_coverage_pct": round(matched / len(rows) * 100, 4) if rows else 0.0,
        **source_totals,
    }
    return results, diagnostics


def update_manifest(path: Path, entries: list[dict]) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"files": []}
    index = {
        (int(item.get("year", 0)), str(item.get("scope", "")), str(item.get("contest_type", ""))): item
        for item in manifest.get("files", [])
    }
    for entry in entries:
        index[(entry["year"], entry["scope"], entry["contest_type"])] = entry
    # Preserve the established manifest order; new contest/year pairs append.
    files = list(index.values())
    path.write_text(json.dumps({"files": files}, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--line-sets", default="2022,2024,2026")
    parser.add_argument("--contests-dir", type=Path, default=ROOT / "data/contests")
    args = parser.parse_args()

    line_sets = [token.strip() for token in args.line_sets.split(",") if token.strip()]
    unknown = sorted(set(line_sets) - set(LINE_SETS))
    if unknown:
        raise ValueError(f"Unknown line sets: {', '.join(unknown)}")

    contest_manifest = json.loads((args.contests_dir / "manifest.json").read_text(encoding="utf-8"))
    contest_entries = [
        entry for entry in contest_manifest.get("files", [])
        if int(entry.get("year", 0)) == args.year
        and not str(entry.get("contest_type", "")).endswith("_model")
    ]
    if not contest_entries:
        raise ValueError(f"No contest slices found for {args.year}")

    for line_set in line_sets:
        spec = LINE_SETS[line_set]
        out_dir: Path = spec["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_entries = []
        for entry in contest_entries:
            contest_type = str(entry["contest_type"])
            source = args.contests_dir / str(entry["file"])
            payload = json.loads(source.read_text(encoding="utf-8"))
            for scope, crosswalk in spec["crosswalks"].items():
                results, diagnostics = aggregate_contest(payload, crosswalk)
                output_name = f"{scope}_{contest_type}_{args.year}.json"
                output = out_dir / output_name
                district_payload = {
                    "year": args.year,
                    "scope": scope,
                    "contest_type": contest_type,
                    "meta": {
                        "source": "modern_precinct_district_crosswalk",
                        "source_contest": str(source.relative_to(ROOT)).replace("\\", "/"),
                        "target_crosswalk": str(crosswalk.relative_to(ROOT)).replace("\\", "/"),
                        "district_lines_year": int(line_set),
                        "district_lines_label": spec["label"],
                        **diagnostics,
                    },
                    "general": {"results": results},
                }
                output.write_text(json.dumps(district_payload, indent=2) + "\n", encoding="utf-8")
                manifest_entries.append({
                    "year": args.year,
                    "scope": scope,
                    "contest_type": contest_type,
                    "file": output_name,
                    "districts": len(results),
                    "district_lines_year": int(line_set),
                    "district_lines_label": spec["label"],
                })
                print(f"Wrote {output.relative_to(ROOT)} ({len(results)} districts)")
        update_manifest(out_dir / "manifest.json", manifest_entries)


if __name__ == "__main__":
    main()
