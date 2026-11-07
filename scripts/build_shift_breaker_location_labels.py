#!/usr/bin/env python3
"""Build plain-language locations for 2020→2026 U.S. Senate shift breakers."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import geopandas as gpd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "mappings" / "district_location_labels.json"
SHIFT_THRESHOLD = 25.0
FULL_THRESHOLD = 0.999
PARTIAL_THRESHOLD = 0.001

PLANS = (
    ("precinct_to_cd118.csv", "district_contests", "congressional", "nc_cd118_tileset.geojson"),
    ("precinct_to_cd119.csv", "district_contests_2024_lines", "congressional", "nc_cd119_tileset.geojson"),
    ("precinct_to_cd2026_sl2025_95.csv", "district_contests_2026_lines", "congressional", "nc_cd2026_sl2025_95_tileset.geojson"),
    ("precinct_to_2022_state_house.csv", "district_contests", "state_house", "nc_state_house_2022_lines_tileset.geojson"),
    ("precinct_to_2024_state_house.csv", "district_contests_2024_lines", "state_house", "nc_state_house_2024_lines_tileset.geojson"),
    ("precinct_to_2022_state_senate.csv", "district_contests", "state_senate", "nc_state_senate_2022_lines_tileset.geojson"),
    ("precinct_to_2024_state_senate.csv", "district_contests_2024_lines", "state_senate", "nc_state_senate_2024_lines_tileset.geojson"),
)

MANUAL_OVERRIDES = {
    "precinct_to_cd118.csv:2": "northern Wake County",
    "precinct_to_cd118.csv:13": "Johnston, southern Wake, most of Harnett, and western Wayne",
}


def normalize_district(value: object) -> str:
    try:
        return str(int(float(str(value).strip())))
    except ValueError:
        return str(value).strip()


def oxford(values: list[str]) -> str:
    if len(values) < 2:
        return values[0] if values else ""
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def breaker_districts(directory: str, scope: str) -> set[str]:
    rows: set[str] = set()
    payloads = []
    for year in (2020, 2026):
        path = ROOT / "data" / directory / f"{scope}_us_senate_{year}.json"
        payloads.append(json.loads(path.read_text(encoding="utf-8"))["general"]["results"])
    for district in set(payloads[0]) | set(payloads[1]):
        old = payloads[0].get(district, {}).get("margin_pct")
        new = payloads[1].get(district, {}).get("margin_pct")
        if old is not None and new is not None and abs(float(new) - float(old)) >= SHIFT_THRESHOLD:
            rows.add(normalize_district(district))
    return rows


def component_shares(crosswalk_name: str) -> dict[str, dict[str, float]]:
    precincts: dict[str, set[str]] = defaultdict(set)
    mass: dict[tuple[str, str], float] = defaultdict(float)
    path = ROOT / "data" / "crosswalks" / crosswalk_name
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            precinct = str(row.get("precinct_key", "")).strip().upper()
            if " - " not in precinct:
                continue
            county = precinct.split(" - ", 1)[0]
            district = normalize_district(row.get("district", ""))
            try:
                weight = float(row.get("area_weight", 0) or 0)
            except ValueError:
                continue
            precincts[county].add(precinct)
            mass[(county, district)] += weight

    out: dict[str, dict[str, float]] = defaultdict(dict)
    for (county, district), value in mass.items():
        denominator = len(precincts[county])
        share = value / denominator if denominator else 0.0
        if share > PARTIAL_THRESHOLD:
            out[district][county] = share
    return dict(out)


def direction_for_piece(piece, county_geometry) -> str:
    if piece.is_empty:
        return "part of"
    center = piece.centroid
    county_center = county_geometry.centroid
    minx, miny, maxx, maxy = county_geometry.bounds
    dx = (center.x - county_center.x) / max(maxx - minx, 1.0)
    dy = (center.y - county_center.y) / max(maxy - miny, 1.0)
    ax, ay = abs(dx), abs(dy)
    if ax < 0.075 and ay < 0.075:
        return "central"
    horizontal = "eastern" if dx > 0 else "western"
    vertical = "northern" if dy > 0 else "southern"
    if ax > ay * 1.45:
        return horizontal
    if ay > ax * 1.45:
        return vertical
    return f"{vertical[:-3]}east" if dx > 0 else f"{vertical[:-3]}west"


def district_column(frame: gpd.GeoDataFrame) -> str:
    for name in ("district_id", "DISTRICT", "SLDLST", "SLDUST", "CDFP"):
        if name in frame.columns:
            return name
    raise ValueError(f"No district identifier in {list(frame.columns)}")


def main() -> int:
    counties = gpd.read_file(ROOT / "data" / "census" / "tl_2020_37_county20.geojson")
    counties = counties.to_crs(32119)
    county_geometry = {
        str(row.NAME20).strip().upper(): row.geometry for row in counties.itertuples(index=False)
    }

    labels: dict[str, dict[str, str]] = {}
    for crosswalk, directory, scope, geometry_name in PLANS:
        targets = breaker_districts(directory, scope)
        shares = component_shares(crosswalk)
        districts = gpd.read_file(ROOT / "data" / "tileset" / geometry_name).to_crs(32119)
        id_col = district_column(districts)
        districts["_district"] = districts[id_col].map(normalize_district)
        district_geometry = districts.dissolve(by="_district").geometry.to_dict()
        plan_labels: dict[str, str] = {}

        for district in sorted(targets, key=int):
            override = MANUAL_OVERRIDES.get(f"{crosswalk}:{district}")
            if override:
                plan_labels[district] = override
                continue
            geometry = district_geometry[district]
            phrases: list[str] = []
            for county, share in sorted(shares.get(district, {}).items()):
                title = county.title()
                county_shape = county_geometry[county]
                piece = geometry.intersection(county_shape)
                spatial_share = piece.area / county_shape.area if county_shape.area else 0.0
                if share >= FULL_THRESHOLD:
                    phrase = title
                elif spatial_share >= 0.55:
                    phrase = f"most of {title}"
                else:
                    phrase = f"{direction_for_piece(piece, county_shape)} {title}"
                phrases.append(phrase)
            plan_labels[district] = oxford(phrases)
        labels[crosswalk] = plan_labels

    payload = {
        "schema": "district_location_labels.v1",
        "method": (
            "County membership and whole/partial shares follow the BEF-derived precinct crosswalks used by "
            "the election aggregation. Whole county >=99.9%; material component >0.1%; 'most' >=55% of county area. "
            "Directional terms compare the district-county intersection centroid with the county geometry."
        ),
        "manual_overrides": MANUAL_OVERRIDES,
        "plans": labels,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {sum(map(len, labels.values()))} labels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
