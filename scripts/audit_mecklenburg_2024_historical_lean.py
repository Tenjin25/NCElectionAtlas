#!/usr/bin/env python3
"""Summarize 2000-era place composition and 2002/2004 lean by 2024 NC House district."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd
from shapely.geometry import mapping, shape


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "data/reports/urban_sf1_historical"
SF1 = ROOT / "data/reports/nc_block_vap_geography_2000_sf1.csv"
COUNTY_GEO = ROOT / "data/census/tl_2020_37_county20.geojson"
CONFIG = {
    (2022, "state_house"): {
        "assignment": ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv",
        "geometry": ROOT / "data/tileset/nc_state_house_2022_lines_tileset.geojson",
        "property": "DISTRICT",
        "label": "house",
    },
    (2022, "state_senate"): {
        "assignment": ROOT / "data/tmp/block_assign_extract/SL 2022-2.csv",
        "geometry": ROOT / "data/tileset/nc_state_senate_2022_lines_tileset.geojson",
        "property": "DISTRICT",
        "label": "senate",
    },
    (2024, "state_house"): {
        "assignment": ROOT / "data/crosswalks/block20_to_2024_state_house.csv",
        "geometry": ROOT / "data/tileset/nc_state_house_2024_lines_tileset.geojson",
        "property": "DISTRICT",
        "label": "house",
    },
    (2024, "state_senate"): {
        "assignment": ROOT / "data/crosswalks/block20_to_2024_state_senate.csv",
        "geometry": ROOT / "data/tileset/nc_state_senate_2024_lines_tileset.geojson",
        "property": "DISTRICT",
        "label": "senate",
    },
}

PLACE_NAMES = {
    "12000": "Charlotte",
    "14700": "Cornelius",
    "16400": "Davidson",
    "33120": "Huntersville",
    "41960": "Matthews",
    "43480": "Mint Hill",
    "52220": "Pineville",
    "99999": "Remainder/unincorporated",
}
NORTH_PLACES = {"14700", "16400", "33120"}
SOUTH_SUBURBAN_PLACES = {"41960", "43480", "52220"}


def load_weights_module():
    path = ROOT / "scripts/build_urban_sf1_historical_legislative_weights.py"
    spec = importlib.util.spec_from_file_location("urban_weights", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result_map(line_year: int, filename: str) -> dict[str, dict]:
    path = ROOT / f"data/district_contests_urban_sf1_{line_year}_lines" / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["general"]["results"]


def norm_district(value: object) -> str:
    text = str(value or "").strip()
    return str(int(text)) if text.isdigit() else text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--line-year", type=int, choices=(2022, 2024), default=2024)
    parser.add_argument(
        "--chamber", choices=("state_house", "state_senate"), default="state_house"
    )
    args = parser.parse_args()
    config = CONFIG[(args.line_year, args.chamber)]
    label = config["label"]
    out_csv = REPORT_DIR / f"mecklenburg_{args.line_year}_{label}_historical_lean.csv"
    out_geojson = REPORT_DIR / f"mecklenburg_{args.line_year}_{label}_historical_lean.geojson"
    out_json = REPORT_DIR / f"mecklenburg_{args.line_year}_{label}_historical_lean.json"
    weights = load_weights_module()
    vap = pd.read_csv(SF1, dtype=str).fillna("")
    vap = vap[vap["county_fips_2000"] == "119"].copy()
    vap["blk2000ge"] = weights.clean_geoid(vap["block_geoid00"])
    vap["vap_count_2000"] = pd.to_numeric(
        vap["vap_count_2000"], errors="coerce"
    ).fillna(0.0)
    bridge = weights.load_fractional_bridge(
        ROOT / "data/census/nhgis_blk2000_blk2010_37/nhgis_blk2000_blk2010_37.csv",
        ROOT / "data/census/nhgis_blk2010_blk2020_37/nhgis_blk2010_blk2020_37.csv",
        {"119"},
    )
    assignment = weights.load_assignment(config["assignment"])
    flow = (
        bridge.merge(assignment, on="blk2020ge", how="inner")
        .merge(
            vap[["blk2000ge", "place_fips_2000", "vap_count_2000"]],
            on="blk2000ge",
            how="inner",
        )
    )
    flow["district"] = flow["district"].map(norm_district)
    flow["vap_flow"] = flow["vap_count_2000"] * flow["weight"]
    by_place = (
        flow.groupby(["district", "place_fips_2000"], as_index=False)["vap_flow"]
        .sum()
    )

    county_payload = json.loads(COUNTY_GEO.read_text(encoding="utf-8"))
    county_feature = next(
        feature
        for feature in county_payload["features"]
        if feature["properties"].get("COUNTYFP20") == "119"
    )
    county_shape = shape(county_feature["geometry"])
    district_payload = json.loads(config["geometry"].read_text(encoding="utf-8"))
    clipped: dict[str, object] = {}
    for feature in district_payload["features"]:
        district = norm_district(feature["properties"].get(config["property"]))
        intersection = shape(feature["geometry"]).intersection(county_shape)
        if not intersection.is_empty and intersection.area > 1e-8:
            clipped[district] = intersection

    senate_2002 = result_map(
        args.line_year, f"{args.chamber}_us_senate_2002.json"
    )
    president_2004 = result_map(
        args.line_year, f"{args.chamber}_president_2004.json"
    )
    governor_2004 = result_map(
        args.line_year, f"{args.chamber}_governor_2004.json"
    )
    rows = []
    features = []
    for district in sorted(clipped, key=int):
        places = by_place[by_place["district"] == district].copy()
        total = float(places["vap_flow"].sum())
        place_values = {
            row.place_fips_2000: float(row.vap_flow)
            for row in places.itertuples(index=False)
        }
        share = lambda codes: (
            100 * sum(place_values.get(code, 0.0) for code in codes) / total
            if total
            else 0.0
        )
        charlotte_share = share({"12000"})
        north_share = share(NORTH_PLACES)
        south_suburban_share = share(SOUTH_SUBURBAN_PLACES)
        remainder_share = share({"99999"})
        geom = clipped[district]
        centroid = geom.centroid
        place_summary = "; ".join(
            f"{PLACE_NAMES.get(code, 'Other place')}:{100 * value / total:.1f}%"
            for code, value in sorted(
                place_values.items(), key=lambda item: (-item[1], item[0])
            )[:4]
            if total
        )
        row = {
            "district": district,
            "centroid_lon": round(centroid.x, 6),
            "centroid_lat": round(centroid.y, 6),
            "sf1_2000_vap_flow": round(total, 2),
            "charlotte_2000_share_pct": round(charlotte_share, 2),
            "north_towns_2000_share_pct": round(north_share, 2),
            "south_suburbs_2000_share_pct": round(south_suburban_share, 2),
            "remainder_2000_share_pct": round(remainder_share, 2),
            "top_2000_places": place_summary,
            "senate_2002_margin_pct": senate_2002[district]["margin_pct"],
            "senate_2002_winner": senate_2002[district]["winner"],
            "president_2004_margin_pct": president_2004[district]["margin_pct"],
            "president_2004_winner": president_2004[district]["winner"],
            "governor_2004_margin_pct": governor_2004[district]["margin_pct"],
            "governor_2004_winner": governor_2004[district]["winner"],
        }
        rows.append(row)
        features.append(
            {
                "type": "Feature",
                "properties": row,
                "geometry": mapping(geom.simplify(0.00015, preserve_topology=True)),
            }
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    out_geojson.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": features,
                "county_boundary": mapping(
                    county_shape.simplify(0.0002, preserve_topology=True)
                ),
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    summary = {
        "schema": "mecklenburg_2024_legislative_historical_lean.v1",
        "line_year": args.line_year,
        "chamber": args.chamber,
        "production_modified": False,
        "districts": rows,
        "south_mecklenburg_candidates": [
            row
            for row in rows
            if row["centroid_lat"] < 35.19
            or row["south_suburbs_2000_share_pct"] >= 5
        ],
        "output_csv": str(out_csv.relative_to(ROOT)).replace("\\", "/"),
        "output_geojson": str(out_geojson.relative_to(ROOT)).replace("\\", "/"),
    }
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
