#!/usr/bin/env python3
"""Build staging-only Mecklenburg 2000-VTD legislative weights.

The production bridge treats later SBE precinct codes as historical identity.
This pilot instead:

1. reads each block's actual VTD code from the Census 2000 SF1 geo header;
2. weights those blocks with Census 2000 SF1 voting-age population;
3. preserves fractional NHGIS 2000->2010->2020 block relationships; and
4. aggregates the resulting population flow into the 2022 and 2024 plans.

The output keys retain the existing three-digit Mecklenburg key convention so
the election pipeline can consume them, but no SBE 2006 geometry is used.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd

from build_block_crosswalk_to_precinct_vintage import assign_blocks, load_precinct_polygons


ROOT = Path(__file__).resolve().parents[1]
COUNTY_FIPS = "119"
COUNTY_NAME = "MECKLENBURG"
HOUSE_SCOPE = "2022_state_house_mqp"
SENATE_SCOPE = "2022_state_senate_mqp"
HOUSE_2024_SCOPE = "2024_state_house"
SENATE_2024_SCOPE = "2024_state_senate"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks00", type=Path, default=ROOT / "data/tl_2008_37_tabblock00.zip")
    parser.add_argument("--sbe2006-shp", type=Path, default=ROOT / "data/Precincts2006Gen/Precincts2006Gen.shp")
    parser.add_argument(
        "--vap00-csv",
        type=Path,
        default=ROOT / "data/reports/mecklenburg_block_vap_2000_sf1.csv",
    )
    parser.add_argument(
        "--results-2000-csv",
        type=Path,
        default=ROOT / "data/2000/20001107__nc__general__precinct.csv",
    )
    parser.add_argument(
        "--precinct-overrides-csv",
        type=Path,
        default=ROOT / "data/reports/mecklenburg_2000_2002_alias_experiment_precinct_overrides.csv",
    )
    parser.add_argument(
        "--nhgis-00-10",
        type=Path,
        default=ROOT / "data/census/nhgis_blk2000_blk2010_37/nhgis_blk2000_blk2010_37.csv",
    )
    parser.add_argument(
        "--nhgis-10-20",
        type=Path,
        default=ROOT / "data/census/nhgis_blk2010_blk2020_37/nhgis_blk2010_blk2020_37.csv",
    )
    parser.add_argument(
        "--house-assignment",
        type=Path,
        default=ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv",
    )
    parser.add_argument(
        "--senate-assignment",
        type=Path,
        default=ROOT / "data/tmp/block_assign_extract/SL 2022-2.csv",
    )
    parser.add_argument(
        "--house-2024-assignment",
        type=Path,
        default=ROOT / "data/crosswalks/block20_to_2024_state_house.csv",
    )
    parser.add_argument(
        "--senate-2024-assignment",
        type=Path,
        default=ROOT / "data/crosswalks/block20_to_2024_state_senate.csv",
    )
    parser.add_argument(
        "--base-weights-json",
        type=Path,
        default=ROOT / "data/mappings/sbe2006_to_modern_district_weights.json",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=ROOT / "data/reports/sbe2006_to_legislative_weights_mecklenburg_vap2000_fractional.json",
    )
    parser.add_argument(
        "--out-comparison-csv",
        type=Path,
        default=ROOT / "data/reports/mecklenburg_vap2000_fractional_legislative_weight_comparison.csv",
    )
    return parser.parse_args()


def clean_geoid(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.extract(r"(\d{15})", expand=False)


def clean_district(value: object) -> str:
    text = str(value or "").strip()
    return text.lstrip("0") or "0"


def precinct_code(value: str) -> str:
    match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)\b", value or "")
    return match.group(1) if match else ""


def load_override_keys(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("year") or "") != "2000":
                continue
            raw = str(row.get("raw_precinct_key") or "")
            canonical = str(row.get("canonical_precinct_key") or "")
            if not raw.upper().startswith(f"{COUNTY_NAME} - "):
                continue
            code = precinct_code(raw.split(" - ", 1)[-1])
            if code and canonical.upper().startswith(f"{COUNTY_NAME} - "):
                out[code] = canonical
    return out


def load_election_cells(results_path: Path, overrides_path: Path) -> pd.DataFrame:
    """Map every 2000 election precinct to its ballot's H/S/CD geography cell."""
    assignments: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"house": set(), "senate": set(), "congressional": set()}
    )
    with results_path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("county") or "").strip().upper() != COUNTY_NAME:
                continue
            code = precinct_code(str(row.get("precinct") or ""))
            if not code:
                continue
            office = str(row.get("office") or "").strip().upper()
            district = clean_district(row.get("district"))
            if office.startswith("HOUSE DISTRICT "):
                assignments[code]["house"].add(district)
            elif office.startswith("SENATE DISTRICT "):
                assignments[code]["senate"].add(district)
            elif office.startswith("US HOUSE OF REP. DISTRICT "):
                assignments[code]["congressional"].add(district)

    override_keys = load_override_keys(overrides_path)
    rows: list[dict[str, str]] = []
    for code, chambers in assignments.items():
        if any(len(chambers[name]) != 1 for name in chambers):
            raise ValueError(f"Ambiguous/incomplete 2000 district cell for precinct {code}: {chambers}")
        key = override_keys.get(code, f"{COUNTY_NAME} - {code.zfill(3)}")
        house = next(iter(chambers["house"]))
        senate = next(iter(chambers["senate"]))
        congressional = next(iter(chambers["congressional"]))
        rows.append(
            {
                "precinct_id": key,
                "cell_id": f"H{house}|S{senate}|C{congressional}",
                "source_house": house,
                "source_senate": senate,
                "source_congressional": congressional,
            }
        )
    return pd.DataFrame(rows)


def expand_cell_results(
    entries: dict[str, list[dict[str, object]]],
    detail: pd.DataFrame,
    election_cells: pd.DataFrame,
) -> tuple[dict[str, list[dict[str, object]]], pd.DataFrame]:
    cell_to_precincts = (
        election_cells.groupby("cell_id")["precinct_id"].apply(list).to_dict()
    )
    expanded_entries: dict[str, list[dict[str, object]]] = {}
    for cell_id, values in entries.items():
        for precinct_id in cell_to_precincts.get(cell_id, []):
            expanded_entries[str(precinct_id)] = copy.deepcopy(values)
    expanded_detail = detail.rename(columns={"precinct_id": "cell_id"}).merge(
        election_cells[["cell_id", "precinct_id"]], on="cell_id", how="inner"
    )
    return expanded_entries, expanded_detail.drop(columns=["cell_id"])


def load_mecklenburg_blocks(path: Path) -> gpd.GeoDataFrame:
    source = f"zip://{path.as_posix()}" if path.suffix.lower() == ".zip" else path
    blocks = gpd.read_file(source)
    geoid_col = next(
        col for col in ("GEOID00", "GEOID", "BLOCKID", "BLKIDFP00", "BLKIDFP") if col in blocks.columns
    )
    county_col = next(col for col in ("COUNTYFP00", "COUNTYFP", "COUNTY") if col in blocks.columns)
    blocks = blocks[[geoid_col, county_col, "geometry"]].rename(
        columns={geoid_col: "block_geoid20", county_col: "countyfp20"}
    )
    blocks["block_geoid20"] = clean_geoid(blocks["block_geoid20"])
    blocks["countyfp20"] = blocks["countyfp20"].astype(str).str.zfill(3)
    blocks = blocks[
        (blocks["countyfp20"] == COUNTY_FIPS) & blocks["block_geoid20"].notna()
    ].copy()
    if blocks["block_geoid20"].duplicated().any():
        blocks = blocks.dissolve(by=["block_geoid20", "countyfp20"], as_index=False)
    return blocks


def load_block00_precinct_map(blocks: gpd.GeoDataFrame, sbe_path: Path) -> pd.DataFrame:
    precincts = load_precinct_polygons(sbe_path, "sbe_2006")
    precincts = precincts[precincts["precinct_id"].str.startswith(f"{COUNTY_NAME} - ")].copy()
    assigned = assign_blocks(blocks, precincts).rename(columns={"block_geoid20": "blk2000ge"})
    assigned["blk2000ge"] = clean_geoid(assigned["blk2000ge"])
    return assigned[["blk2000ge", "precinct_id"]].drop_duplicates("blk2000ge")


def load_fractional_bridge(path00_10: Path, path10_20: Path) -> pd.DataFrame:
    a_parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path00_10,
        dtype=str,
        usecols=["blk2000ge", "blk2010ge", "weight"],
        chunksize=250_000,
    ):
        chunk["blk2000ge"] = clean_geoid(chunk["blk2000ge"])
        chunk = chunk[chunk["blk2000ge"].str.startswith(f"37{COUNTY_FIPS}", na=False)].copy()
        if not chunk.empty:
            a_parts.append(chunk)
    if not a_parts:
        raise ValueError("No Mecklenburg rows in the NHGIS 2000->2010 bridge.")
    a = pd.concat(a_parts, ignore_index=True)
    a["blk2010ge"] = clean_geoid(a["blk2010ge"])
    a["w1"] = pd.to_numeric(a["weight"], errors="coerce").fillna(0.0)
    a = a[
        a["blk2010ge"].str.startswith(f"37{COUNTY_FIPS}", na=False) & (a["w1"] > 0)
    ].copy()
    block10_ids = set(a["blk2010ge"])

    b_parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path10_20,
        dtype=str,
        usecols=["blk2010ge", "blk2020ge", "weight"],
        chunksize=250_000,
    ):
        chunk["blk2010ge"] = clean_geoid(chunk["blk2010ge"])
        chunk = chunk[chunk["blk2010ge"].isin(block10_ids)].copy()
        if not chunk.empty:
            b_parts.append(chunk)
    if not b_parts:
        raise ValueError("No Mecklenburg-linked rows in the NHGIS 2010->2020 bridge.")
    b = pd.concat(b_parts, ignore_index=True)
    b["blk2020ge"] = clean_geoid(b["blk2020ge"])
    b["w2"] = pd.to_numeric(b["weight"], errors="coerce").fillna(0.0)
    b = b[
        b["blk2020ge"].str.startswith(f"37{COUNTY_FIPS}", na=False) & (b["w2"] > 0)
    ].copy()

    chained = a[["blk2000ge", "blk2010ge", "w1"]].merge(
        b[["blk2010ge", "blk2020ge", "w2"]], on="blk2010ge", how="inner"
    )
    chained["weight"] = chained["w1"] * chained["w2"]
    chained = (
        chained[chained["weight"] > 0]
        .groupby(["blk2000ge", "blk2020ge"], as_index=False)["weight"]
        .sum()
    )
    den = chained.groupby("blk2000ge")["weight"].transform("sum")
    chained["weight"] = chained["weight"] / den
    return chained


def load_assignment(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    if {"Block", "District"}.issubset(df.columns):
        block_col, district_col = "Block", "District"
    elif {"block_geoid20", "district"}.issubset(df.columns):
        block_col, district_col = "block_geoid20", "district"
    elif {"GEOID", "CDFP"}.issubset(df.columns):
        block_col, district_col = "GEOID", "CDFP"
    else:
        raise ValueError(
            f"Unsupported block assignment columns in {path}: {list(df.columns)}"
        )
    out = df[[block_col, district_col]].copy()
    out.columns = ["blk2020ge", "district"]
    out["blk2020ge"] = clean_geoid(out["blk2020ge"])
    out["district"] = out["district"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    return out.dropna(subset=["blk2020ge"]).drop_duplicates("blk2020ge")


def scope_entries(
    flow: pd.DataFrame,
    assignment: pd.DataFrame,
    *,
    prefix: str,
    width: int,
    name_template: str,
) -> tuple[dict[str, list[dict[str, object]]], pd.DataFrame]:
    joined = flow.merge(assignment, on="blk2020ge", how="inner")
    joined["mass"] = joined["vap_count_2000"] * joined["weight"]
    joined["fallback_mass"] = joined["weight"]
    grouped = (
        joined.groupby(["precinct_id", "district"], as_index=False)
        .agg(
            mass=("mass", "sum"),
            fallback_mass=("fallback_mass", "sum"),
            block_count=("blk2020ge", "nunique"),
        )
    )
    totals = grouped.groupby("precinct_id", as_index=False).agg(
        mass_total=("mass", "sum"),
        fallback_total=("fallback_mass", "sum"),
    )
    grouped = grouped.merge(totals, on="precinct_id", how="left")
    grouped["weight_source"] = "census2000_sf1_vtd_vap_nhgis_fractional"
    zero = grouped["mass_total"] <= 0
    grouped["share"] = grouped["mass"] / grouped["mass_total"].where(~zero, 1)
    grouped.loc[zero, "share"] = (
        grouped.loc[zero, "fallback_mass"] / grouped.loc[zero, "fallback_total"].replace(0, pd.NA)
    )
    grouped["share"] = grouped["share"].fillna(0.0)

    entries: dict[str, list[dict[str, object]]] = {}
    for precinct_id, rows in grouped.groupby("precinct_id", sort=True):
        target_rows: list[dict[str, object]] = []
        rows = rows.sort_values(["share", "district"], ascending=[False, True])
        raw_shares = rows["share"].tolist()
        rounded = [round(float(value), 10) for value in raw_shares]
        if rounded:
            rounded[-1] = round(rounded[-1] + (1.0 - sum(rounded)), 10)
        for (_, row), share in zip(rows.iterrows(), rounded):
            code = str(row["district"]).zfill(width)
            number = str(int(code)) if code.isdigit() else code
            target_rows.append(
                {
                    "district": str(row["district"]),
                    "district_label": f"{prefix}-{code}",
                    "district_name": name_template.format(number=number),
                    "share": share,
                    "block_share": share,
                    "block_count": int(row["block_count"]),
                    "vap_count": round(float(row["mass"]), 6),
                    "weight_source": str(row["weight_source"]),
                }
            )
        entries[str(precinct_id)] = target_rows
    return entries, grouped


def old_share_rows(payload: dict, scope_name: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    precincts = payload["scopes"][scope_name]["precincts"]
    for precinct_id, entries in precincts.items():
        if not precinct_id.startswith(f"{COUNTY_NAME} - "):
            continue
        for entry in entries:
            rows.append(
                {
                    "scope": scope_name,
                    "precinct_id": precinct_id,
                    "district": str(entry.get("district", "")),
                    "old_share": float(entry.get("share", 0)),
                }
            )
    return rows


def main() -> None:
    args = parse_args()
    vap = pd.read_csv(args.vap00_csv, dtype=str).fillna("")
    vap["blk2000ge"] = clean_geoid(vap["block_geoid00"])
    vap["vap_count_2000"] = pd.to_numeric(vap["vap_count_2000"], errors="coerce").fillna(0.0)
    if "vtd_code_2000" not in vap.columns:
        raise ValueError(
            "The SF1 extract lacks vtd_code_2000; rerun extract_census2000_block_vap.py."
        )
    required_geo = {"sldl_2000", "sldu_2000", "cd106_2000"}
    missing_geo = required_geo - set(vap.columns)
    if missing_geo:
        raise ValueError(f"The SF1 extract lacks geographic columns: {sorted(missing_geo)}")
    election_cells = load_election_cells(args.results_2000_csv, args.precinct_overrides_csv)
    sf_house = vap["sldl_2000"].map(clean_district)
    sf_senate = vap["sldu_2000"].map(clean_district)
    sf_cd = vap["cd106_2000"].map(clean_district)
    block_precinct = vap[["blk2000ge"]].copy()
    block_precinct["precinct_id"] = (
        "H" + sf_house + "|S" + sf_senate + "|C" + sf_cd
    )
    block_precinct = block_precinct.drop_duplicates("blk2000ge")
    missing_cells = set(election_cells["cell_id"]) - set(block_precinct["precinct_id"])
    if missing_cells:
        raise ValueError(f"Election district cells absent from SF1 blocks: {sorted(missing_cells)}")
    bridge = load_fractional_bridge(args.nhgis_00_10, args.nhgis_10_20)

    flow = bridge.merge(block_precinct, on="blk2000ge", how="inner").merge(
        vap[["blk2000ge", "vap_count_2000"]], on="blk2000ge", how="left"
    )
    flow["vap_count_2000"] = flow["vap_count_2000"].fillna(0.0)
    if flow.empty:
        raise ValueError("No fractional block flows survived the precinct/VAP joins.")
    source_vap_total = float(vap["vap_count_2000"].sum())
    bridged_block_ids = set(flow["blk2000ge"])
    bridged_vap_total = float(
        vap.loc[vap["blk2000ge"].isin(bridged_block_ids), "vap_count_2000"].sum()
    )

    house_entries, house_detail = scope_entries(
        flow,
        load_assignment(args.house_assignment),
        prefix="HD",
        width=3,
        name_template="State House District {number}",
    )
    senate_entries, senate_detail = scope_entries(
        flow,
        load_assignment(args.senate_assignment),
        prefix="SD",
        width=2,
        name_template="State Senate District {number}",
    )
    house_2024_entries, house_2024_detail = scope_entries(
        flow,
        load_assignment(args.house_2024_assignment),
        prefix="HD",
        width=3,
        name_template="State House District {number}",
    )
    senate_2024_entries, senate_2024_detail = scope_entries(
        flow,
        load_assignment(args.senate_2024_assignment),
        prefix="SD",
        width=2,
        name_template="State Senate District {number}",
    )
    house_entries, house_detail = expand_cell_results(
        house_entries, house_detail, election_cells
    )
    senate_entries, senate_detail = expand_cell_results(
        senate_entries, senate_detail, election_cells
    )
    house_2024_entries, house_2024_detail = expand_cell_results(
        house_2024_entries, house_2024_detail, election_cells
    )
    senate_2024_entries, senate_2024_detail = expand_cell_results(
        senate_2024_entries, senate_2024_detail, election_cells
    )

    base = json.loads(args.base_weights_json.read_text(encoding="utf-8"))
    output = copy.deepcopy(base)
    output["description"] = (
        str(base.get("description") or "")
        + " Mecklenburg 2022/2024 legislative entries replaced by a staging-only Census 2000 "
        "VAP + fractional NHGIS block-flow pilot."
    ).strip()
    output["pilot"] = {
        "county": COUNTY_NAME,
        "county_fips": COUNTY_FIPS,
        "source_vap": str(args.vap00_csv.relative_to(ROOT)).replace("\\", "/"),
        "source_precinct_geometry": None,
        "source_precinct_identifier": (
            "2000 election House/Senate/CD ballot cell matched to the same SF1 "
            "geographic-header fields; numeric VTD IDs are not joined directly"
        ),
        "method": "census2000_election_district_cell_sf1_vap_nhgis_fractional",
        "source_blocks": int(vap["blk2000ge"].nunique()),
        "source_election_precincts": int(election_cells["precinct_id"].nunique()),
        "source_district_cells": int(election_cells["cell_id"].nunique()),
        "assigned_source_blocks": int(block_precinct["precinct_id"].notna().sum()),
        "bridged_source_blocks": int(len(bridged_block_ids)),
        "source_vap_total": source_vap_total,
        "bridged_source_vap": bridged_vap_total,
        "bridged_source_vap_pct": round(
            100.0 * bridged_vap_total / source_vap_total if source_vap_total else 0.0, 6
        ),
        "production_safe": False,
    }

    scope_entries_by_name = (
        (HOUSE_SCOPE, house_entries),
        (SENATE_SCOPE, senate_entries),
        (HOUSE_2024_SCOPE, house_2024_entries),
        (SENATE_2024_SCOPE, senate_2024_entries),
    )
    for scope_name, entries in scope_entries_by_name:
        scope = output["scopes"][scope_name]
        precincts = {
            key: value
            for key, value in scope["precincts"].items()
            if not key.startswith(f"{COUNTY_NAME} - ")
        }
        precincts.update(entries)
        scope["precincts"] = dict(sorted(precincts.items()))
        scope["mecklenburg_weight_source"] = (
            "census2000_election_district_cell_sf1_vap_nhgis_fractional"
        )

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    old_rows = pd.DataFrame(
        old_share_rows(base, HOUSE_SCOPE)
        + old_share_rows(base, SENATE_SCOPE)
        + old_share_rows(base, HOUSE_2024_SCOPE)
        + old_share_rows(base, SENATE_2024_SCOPE)
    )
    new_rows = pd.concat(
        [
            house_detail.assign(scope=HOUSE_SCOPE),
            senate_detail.assign(scope=SENATE_SCOPE),
            house_2024_detail.assign(scope=HOUSE_2024_SCOPE),
            senate_2024_detail.assign(scope=SENATE_2024_SCOPE),
        ],
        ignore_index=True,
    )[["scope", "precinct_id", "district", "share", "mass", "block_count", "weight_source"]]
    new_rows = new_rows.rename(columns={"share": "new_share", "mass": "vap2000_flow"})
    comparison = old_rows.merge(
        new_rows, on=["scope", "precinct_id", "district"], how="outer"
    ).fillna({"old_share": 0.0, "new_share": 0.0, "vap2000_flow": 0.0, "block_count": 0})
    comparison["share_delta"] = comparison["new_share"] - comparison["old_share"]
    comparison = comparison.sort_values(
        ["scope", "precinct_id", "new_share", "district"],
        ascending=[True, True, False, True],
    )
    comparison.to_csv(args.out_comparison_csv, index=False)

    print(
        f"Wrote {args.out_json}; source blocks={len(vap):,}; "
        f"cell-assigned={block_precinct['precinct_id'].notna().sum():,}; "
        f"fractional flows={len(flow):,}; House precincts={len(house_entries):,}; "
        f"Senate precincts={len(senate_entries):,}; "
        f"2024 House precincts={len(house_2024_entries):,}; "
        f"2024 Senate precincts={len(senate_2024_entries):,}"
    )
    print(f"Wrote {args.out_comparison_csv}")


if __name__ == "__main__":
    main()
