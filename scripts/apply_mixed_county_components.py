#!/usr/bin/env python3
"""Build and audit districts containing whole and split county components.

The district-result builders reconcile precinct-sort votes to official county
totals before projecting them into districts.  Consequently, a county that is
entirely inside one district contributes its exact county total, even when the
rest of that district contains only part of another county.  This script makes
that rule explicit in one shared plan-component catalog for both live plans.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FULL_THRESHOLD = 0.999
PARTIAL_THRESHOLD = 0.001
PLAN_SCOPES = (
    (
        "2022_state_house",
        ROOT / "data" / "crosswalks" / "precinct_to_2022_state_house.csv",
        ROOT / "data" / "district_contests",
        "state_house_",
    ),
    (
        "2024_state_house",
        ROOT / "data" / "crosswalks" / "precinct_to_2024_state_house.csv",
        ROOT / "data" / "district_contests_2024_lines",
        "state_house_",
    ),
    (
        "2022_state_senate",
        ROOT / "data" / "crosswalks" / "precinct_to_2022_state_senate.csv",
        ROOT / "data" / "district_contests",
        "state_senate_",
    ),
    (
        "2024_state_senate",
        ROOT / "data" / "crosswalks" / "precinct_to_2024_state_senate.csv",
        ROOT / "data" / "district_contests_2024_lines",
        "state_senate_",
    ),
)


def normalize_district(raw: object) -> str:
    value = str(raw or "").strip()
    try:
        return str(int(float(value)))
    except ValueError:
        return value


def build_components(crosswalk_path: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return whole and material partial counties for each mixed district."""
    intersections: dict[tuple[str, str], float] = defaultdict(float)
    precinct_areas: dict[tuple[str, str], float] = {}

    with crosswalk_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            precinct_key = str(row.get("precinct_key", "")).strip().upper()
            if " - " not in precinct_key:
                continue
            county = precinct_key.split(" - ", 1)[0]
            district = normalize_district(row.get("district"))
            if not district:
                continue
            intersections[(county, district)] += float(row.get("intersect_area_m2", 0) or 0)
            precinct_areas[(county, precinct_key)] = float(row.get("precinct_area_m2", 0) or 0)

    county_areas: dict[str, float] = defaultdict(float)
    for (county, _), area in precinct_areas.items():
        county_areas[county] += area

    whole: dict[str, list[str]] = defaultdict(list)
    partial: dict[str, list[str]] = defaultdict(list)
    for (county, district), area in intersections.items():
        county_area = county_areas.get(county, 0.0)
        if county_area <= 0:
            continue
        share = area / county_area
        if share >= FULL_THRESHOLD:
            whole[district].append(county)
        elif share > PARTIAL_THRESHOLD:
            partial[district].append(county)

    mixed_districts = set(whole) & set(partial)
    exact = {district: sorted(set(whole[district])) for district in mixed_districts}
    allocated = {district: sorted(set(partial[district])) for district in mixed_districts}
    return exact, allocated


def district_sort_key(value: str) -> tuple[int, str]:
    try:
        return int(value), value
    except ValueError:
        return 10**9, value


def ordered(mapping: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: mapping[key] for key in sorted(mapping, key=district_sort_key)}


META_KEYS = (
    "mixed_county_component_plan",
    "mixed_county_exact_components",
    "mixed_county_allocated_components",
    "mixed_county_component_method",
)


def clean_result_metadata(directory: Path, prefix: str) -> int:
    """Remove metadata written by the initial per-contest implementation."""
    changed = 0
    for path in sorted(directory.glob(f"{prefix}*.json")):
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        meta = payload.get("meta", {})
        if not isinstance(meta, dict) or not any(key in meta for key in META_KEYS):
            continue
        for key in META_KEYS:
            meta.pop(key, None)
        pretty = "\n" in raw.strip()
        text = json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False)
        if pretty:
            text += "\n"
        path.write_text(text, encoding="utf-8")
        changed += 1
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--clean-result-metadata", action="store_true")
    args = parser.parse_args()

    report = []
    catalog = {
        "schema": "mixed_county_components.v1",
        "full_county_threshold": FULL_THRESHOLD,
        "material_partial_county_threshold": PARTIAL_THRESHOLD,
        "method": (
            "Whole-county components retain canonical county totals; only partial-"
            "county components are allocated through calibrated precinct/block "
            "crosswalks. Shares at or below the material-partial threshold are "
            "treated as geometry slivers."
        ),
        "plans": {},
    }
    for plan, crosswalk, directory, prefix in PLAN_SCOPES:
        cleaned = clean_result_metadata(directory, prefix) if args.clean_result_metadata else 0
        exact, allocated = build_components(crosswalk)
        catalog["plans"][plan] = {
            "crosswalk": str(crosswalk.relative_to(ROOT)).replace("\\", "/"),
            "exact_components": ordered(exact),
            "allocated_components": ordered(allocated),
        }
        report.append(
            {
                "plan": plan,
                "mixed_districts": len(exact),
                "exact_county_components": sum(len(value) for value in exact.values()),
                "cleaned_result_files": cleaned,
            }
        )

    output_path = ROOT / "data" / "mappings" / "mixed_county_components.json"
    rendered = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    changed = not output_path.exists() or output_path.read_text(encoding="utf-8") != rendered
    if args.write:
        output_path.write_text(rendered, encoding="utf-8")

    print(json.dumps({
        "mode": "write" if args.write else "audit",
        "catalog": str(output_path.relative_to(ROOT)),
        "catalog_changed": changed,
        "plans": report,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
