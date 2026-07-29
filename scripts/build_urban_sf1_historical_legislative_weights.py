#!/usr/bin/env python3
"""Build staging weights for NC urban counties in 2000, 2002, and 2004.

2000 election precinct numbers are not assumed to equal Census VTD numbers.
Each precinct is instead linked to the SF1 blocks in its contemporaneous
House/Senate/Congressional district cell. For 2002 and 2004, a direct VTD link
is used only when the election prefix resolves uniquely to an SF1 VTD in the
same county. Every accepted historical precinct receives a synthetic staging
key, avoiding accidental reuse of later SBE identifiers.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import re
import sys
import zipfile
from collections import defaultdict
from io import TextIOWrapper
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_district_results_2024_lines import NC_COUNTY_FIPS  # noqa: E402
from build_mecklenburg_2000_vap_legislative_weights import (  # noqa: E402
    clean_district,
    clean_geoid,
    load_assignment,
    scope_entries,
)


YEARS = (2000, 2002, 2004)
RESULTS = {
    2000: ROOT / "data/2000/20001107__nc__general__precinct.csv",
    2002: ROOT / "data/2002/20021105__nc__general__precinct.csv",
    2004: ROOT / "data/2004/20041102__nc__general__precinct.csv",
}
CONTEST_OFFICES = {
    2002: {"US SENATE", "UNITED STATES SENATE"},
    2004: {"PRESIDENT", "PRESIDENT AND VICE PRESIDENT"},
}
SCOPE_CONFIG = (
    (
        "2022_state_house_mqp",
        ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv",
        "HD",
        3,
        "State House District {number}",
    ),
    (
        "2022_state_senate_mqp",
        ROOT / "data/tmp/block_assign_extract/SL 2022-2.csv",
        "SD",
        2,
        "State Senate District {number}",
    ),
    (
        "2022_congressional_cd118",
        ROOT / "data/tmp/block_assign_extract/NC_CD118.csv",
        "CD",
        2,
        "Congressional District {number}",
    ),
    (
        "2024_state_house",
        ROOT / "data/crosswalks/block20_to_2024_state_house.csv",
        "HD",
        3,
        "State House District {number}",
    ),
    (
        "2024_state_senate",
        ROOT / "data/crosswalks/block20_to_2024_state_senate.csv",
        "SD",
        2,
        "State Senate District {number}",
    ),
    (
        "2024_congressional_cd119",
        ROOT / "data/crosswalks/block20_to_cd119.csv",
        "CD",
        2,
        "Congressional District {number}",
    ),
    (
        "2026_congressional_sl2025_95",
        ROOT / "data/tmp/block_assign_extract_2026/NC_CD2026.csv",
        "CD",
        2,
        "Congressional District {number}",
    ),
)
PLAN_ARCHIVES = {
    2002: {
        "house": "House_2002_Court_baf.zip",
        "senate": "Senate_2002_Court_baf.zip",
        "congressional": "Congress_2001_baf.zip",
    },
    2004: {
        "house": "House_2003_baf.zip",
        "senate": "Senate_2003_baf.zip",
        "congressional": "Congress_2001_baf.zip",
    },
}
SBE2006_LINEAGE_ALIASES = [
    {
        "year": "2004",
        "county": "CUMBERLAND",
        "raw_precinct": "CU01 CUMBERLAND #1",
        "canonical_precinct_key": "CUMBERLAND - CUMBERLAND 1A",
        "evidence": "SBE2006 CU01A / CUMBERLAND #1A; no competing CU01B",
    },
    {
        "year": "2004",
        "county": "CUMBERLAND",
        "raw_precinct": "HM01 HOPE MILLS #1",
        "canonical_precinct_key": "CUMBERLAND - HOPE MILLS 1A",
        "evidence": "SBE2006 HM01A / HOPE MILLS #1A; no competing HM01B",
    },
]

# Buncombe's dotted 2004 precinct codes have an unusually complete, explicit
# one-to-one bridge to SBE2006 precincts. Prefer that finer geography to the
# much coarser historical House/Senate plan cells, which cannot preserve the
# modern SD-46/SD-49 split within the county.
PREFER_EXACT_SBE2006_GEOMETRY = {(2004, "BUNCOMBE")}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sf1-csv",
        type=Path,
        default=ROOT / "data/reports/nc_block_vap_geography_2000_sf1.csv",
    )
    parser.add_argument(
        "--aliases-csv",
        type=Path,
        default=ROOT / "data/mappings/legacy_precinct_abbreviation_to_sbe2006.csv",
    )
    parser.add_argument(
        "--production-overrides-csv",
        type=Path,
        default=ROOT / "data/mappings/precinct_key_overrides.csv",
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
        "--base-weights-json",
        type=Path,
        default=ROOT / "data/mappings/sbe2006_to_modern_district_weights.json",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "data/reports/urban_sf1_historical"
    )
    parser.add_argument(
        "--historical-source-root",
        type=Path,
        default=ROOT / "downloads/nc_historical_precinct_sources",
    )
    return parser.parse_args()


def norm(value: object) -> str:
    return " ".join(str(value or "").strip().upper().split())


def code_norm(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]", "", norm(value))
    if text.isdigit():
        return str(int(text))
    return text


def prefix_token(value: str) -> str:
    return str(value or "").strip().split(" ", 1)[0]


def load_alias_evidence(path: Path) -> tuple[dict[int, set[str]], dict[tuple[int, str], set[str]]]:
    counties: dict[int, set[str]] = defaultdict(set)
    tokens: dict[tuple[int, str], set[str]] = defaultdict(set)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            try:
                year = int(row.get("year") or 0)
            except ValueError:
                continue
            if year not in YEARS:
                continue
            county = norm(row.get("county"))
            if not county:
                continue
            counties[year].add(county)
            candidates = [
                row.get("precinct_abbrv"),
                *(str(row.get("alias_values") or "").split(";")),
            ]
            for candidate in candidates:
                compact = code_norm(candidate)
                if compact:
                    tokens[(year, county)].add(compact)
    return counties, tokens


def load_alias_canonical_map(path: Path) -> dict[tuple[int, str, str], set[str]]:
    output: dict[tuple[int, str, str], set[str]] = defaultdict(set)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            try:
                year = int(row.get("year") or 0)
            except ValueError:
                continue
            if year not in YEARS:
                continue
            county = norm(row.get("county"))
            canonical = norm(row.get("sbe2006_key"))
            candidates = [
                row.get("precinct_abbrv"),
                *str(row.get("alias_values") or "").split(";"),
            ]
            for candidate in candidates:
                token = code_norm(candidate)
                if county and canonical and token:
                    output[(year, county, token)].add(canonical)
    return output


def load_fractional_bridge(
    path00_10: Path, path10_20: Path, county_fips: set[str]
) -> pd.DataFrame:
    prefixes = tuple(f"37{value}" for value in sorted(county_fips))
    parts1: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path00_10,
        dtype=str,
        usecols=["blk2000ge", "blk2010ge", "weight"],
        chunksize=250_000,
    ):
        chunk["blk2000ge"] = clean_geoid(chunk["blk2000ge"])
        chunk = chunk[chunk["blk2000ge"].str.startswith(prefixes, na=False)].copy()
        if not chunk.empty:
            parts1.append(chunk)
    a = pd.concat(parts1, ignore_index=True)
    a["blk2010ge"] = clean_geoid(a["blk2010ge"])
    a["w1"] = pd.to_numeric(a["weight"], errors="coerce").fillna(0.0)
    a = a[a["blk2010ge"].str.startswith(prefixes, na=False) & (a["w1"] > 0)].copy()
    ids10 = set(a["blk2010ge"])

    parts2: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path10_20,
        dtype=str,
        usecols=["blk2010ge", "blk2020ge", "weight"],
        chunksize=250_000,
    ):
        chunk["blk2010ge"] = clean_geoid(chunk["blk2010ge"])
        chunk = chunk[chunk["blk2010ge"].isin(ids10)].copy()
        if not chunk.empty:
            parts2.append(chunk)
    b = pd.concat(parts2, ignore_index=True)
    b["blk2020ge"] = clean_geoid(b["blk2020ge"])
    b["w2"] = pd.to_numeric(b["weight"], errors="coerce").fillna(0.0)
    b = b[b["blk2020ge"].str.startswith(prefixes, na=False) & (b["w2"] > 0)].copy()
    chained = a[["blk2000ge", "blk2010ge", "w1"]].merge(
        b[["blk2010ge", "blk2020ge", "w2"]], on="blk2010ge", how="inner"
    )
    chained["weight"] = chained["w1"] * chained["w2"]
    chained = (
        chained[chained["weight"] > 0]
        .groupby(["blk2000ge", "blk2020ge"], as_index=False)["weight"]
        .sum()
    )
    chained["weight"] /= chained.groupby("blk2000ge")["weight"].transform("sum")
    return chained


def collect_2000_precincts(
    path: Path,
    target_counties: set[str],
    sf_vtds: set[tuple[str, str]],
) -> pd.DataFrame:
    assignments: dict[tuple[str, str], dict[str, dict[str, int]]] = defaultdict(
        lambda: {
            "house": defaultdict(int),
            "senate": defaultdict(int),
            "congressional": defaultdict(int),
        }
    )
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            county = norm(row.get("county"))
            if county not in target_counties:
                continue
            raw = str(row.get("precinct") or "").strip()
            office = norm(row.get("office"))
            district = clean_district(row.get("district"))
            votes = int(float(row.get("votes") or 0))
            key = (county, raw)
            if office.startswith("HOUSE DISTRICT "):
                assignments[key]["house"][district] += votes
            elif office.startswith("SENATE DISTRICT "):
                assignments[key]["senate"][district] += votes
            elif office.startswith("US HOUSE OF REP. DISTRICT "):
                assignments[key]["congressional"][district] += votes
    rows: list[dict[str, Any]] = []
    for (county, raw), chamber_totals in assignments.items():
        chambers = {
            name: {
                district
                for district, votes in totals.items()
                if district and votes > 0
            }
            for name, totals in chamber_totals.items()
        }
        # Preserve a uniquely listed zero-turnout district, but ignore
        # zero-filled rows for contests that did not cover the precinct.
        for name, totals in chamber_totals.items():
            listed = {district for district in totals if district}
            if not chambers[name] and len(listed) == 1:
                chambers[name] = listed
        unique = {name: len(values) == 1 for name, values in chambers.items()}
        if not unique["congressional"]:
            continue
        vtd_token = code_norm(prefix_token(raw))
        vtd_prefix = (
            f"{county}|VTD{vtd_token}|"
            if vtd_token and (county, vtd_token) in sf_vtds
            else f"{county}|"
        )
        precise_vtd = vtd_prefix != f"{county}|"
        cd = next(iter(chambers["congressional"]))
        if unique["house"] and unique["senate"]:
            house = next(iter(chambers["house"]))
            senate = next(iter(chambers["senate"]))
            fallback_group_id = f"{county}|HSC|H{house}|S{senate}|C{cd}"
            group_id = (
                f"{vtd_prefix}HSC|H{house}|S{senate}|C{cd}"
                if precise_vtd
                else fallback_group_id
            )
            strategy = (
                "direct_sf1_vtd_election_district_cell_hsc"
                if precise_vtd
                else "election_district_cell_hsc"
            )
        elif unique["senate"]:
            senate = next(iter(chambers["senate"]))
            fallback_group_id = f"{county}|SC|S{senate}|C{cd}"
            group_id = (
                f"{vtd_prefix}SC|S{senate}|C{cd}"
                if precise_vtd
                else fallback_group_id
            )
            strategy = (
                "direct_sf1_vtd_election_district_cell_sc"
                if precise_vtd
                else "election_district_cell_sc"
            )
        elif unique["house"]:
            house = next(iter(chambers["house"]))
            fallback_group_id = f"{county}|HC|H{house}|C{cd}"
            group_id = (
                f"{vtd_prefix}HC|H{house}|C{cd}"
                if precise_vtd
                else fallback_group_id
            )
            strategy = (
                "direct_sf1_vtd_election_district_cell_hc"
                if precise_vtd
                else "election_district_cell_hc"
            )
        else:
            fallback_group_id = f"{county}|C|C{cd}"
            group_id = (
                f"{vtd_prefix}C|C{cd}" if precise_vtd else fallback_group_id
            )
            strategy = (
                "direct_sf1_vtd_election_district_cell_c"
                if precise_vtd
                else "election_district_cell_c"
            )
        rows.append(
            {
                "year": 2000,
                "county": county,
                "raw_precinct": raw,
                "group_id": group_id,
                "fallback_group_id": fallback_group_id,
                "strategy": strategy,
            }
        )
    return pd.DataFrame(rows)


def collect_direct_precincts(
    year: int,
    path: Path,
    target_counties: set[str],
    sf_vtds: set[tuple[str, str]],
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    seen: set[tuple[str, str]] = set()
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            county = norm(row.get("county"))
            office = norm(row.get("office"))
            raw = str(row.get("precinct") or "").strip()
            if county not in target_counties or office not in CONTEST_OFFICES[year]:
                continue
            key = (county, raw)
            if key in seen:
                continue
            seen.add(key)
            raw_prefix = prefix_token(raw)
            token = code_norm(raw_prefix)
            dotted_split = "." in raw_prefix
            if not dotted_split and token and (county, token) in sf_vtds:
                accepted.append(
                    {
                        "year": year,
                        "county": county,
                        "raw_precinct": raw,
                        "group_id": f"{county}|VTD{token}",
                        "strategy": "direct_sf1_vtd",
                    }
                )
            else:
                rejected.append(
                    {
                        "year": str(year),
                        "county": county,
                        "raw_precinct": raw,
                        "prefix_token": raw_prefix,
                        "reason": (
                            "dotted_split_prefix_requires_name_bridge"
                            if dotted_split
                            else "prefix_not_unique_sf1_vtd"
                        ),
                    }
                )
    return pd.DataFrame(accepted), rejected


def district_from_office(row: dict[str, str]) -> tuple[str, str] | None:
    office = norm(row.get("office"))
    chamber = ""
    if office.startswith(("NC HOUSE (", "NC STATE HOUSE DISTRICT ")):
        chamber = "house"
    elif office.startswith(("NC SENATE (", "NC STATE SENATE DISTRICT ")):
        chamber = "senate"
    elif office.startswith("US HOUSE ("):
        chamber = "congressional"
    if not chamber:
        return None
    raw_district = str(row.get("district") or "").strip()
    district = clean_district(raw_district) if raw_district else ""
    if not district:
        match = re.search(r"\b(\d+)(?:ST|ND|RD|TH)?\b", office)
        district = clean_district(match.group(1) if match else "")
    return (chamber, district) if district else None


def collect_plan_cell_precincts(
    year: int,
    path: Path,
    candidates: list[dict[str, str]],
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    candidate_keys = {
        (norm(row["county"]), str(row["raw_precinct"]).strip()) for row in candidates
    }
    assignments: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: {"house": set(), "senate": set(), "congressional": set()}
    )
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            key = (norm(row.get("county")), str(row.get("precinct") or "").strip())
            if key not in candidate_keys:
                continue
            parsed = district_from_office(row)
            if parsed:
                chamber, district = parsed
                assignments[key][chamber].add(district)

    accepted: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    candidate_lookup = {
        (norm(row["county"]), str(row["raw_precinct"]).strip()): row
        for row in candidates
    }
    for key in sorted(candidate_keys):
        chambers = assignments[key]
        unique = {name: len(values) == 1 for name, values in chambers.items()}
        values = {
            name: next(iter(found)) if len(found) == 1 else ""
            for name, found in chambers.items()
        }
        county, raw = key
        if unique["house"] and unique["senate"] and unique["congressional"]:
            group_id = (
                f"{county}|PLANHSC|H{values['house']}|S{values['senate']}"
                f"|C{values['congressional']}"
            )
            strategy = "historical_plan_cell_hsc"
        elif unique["house"] and unique["senate"]:
            group_id = f"{county}|PLANHS|H{values['house']}|S{values['senate']}"
            strategy = "historical_plan_cell_hs"
        elif unique["house"] and unique["congressional"]:
            group_id = f"{county}|PLANHC|H{values['house']}|C{values['congressional']}"
            strategy = "historical_plan_cell_hc"
        elif unique["senate"] and unique["congressional"]:
            group_id = f"{county}|PLANSC|S{values['senate']}|C{values['congressional']}"
            strategy = "historical_plan_cell_sc"
        else:
            original = candidate_lookup[key]
            unresolved.append(
                {
                    **original,
                    "reason": "no_unique_two_way_historical_plan_cell",
                    "house_districts": ";".join(sorted(chambers["house"])),
                    "senate_districts": ";".join(sorted(chambers["senate"])),
                    "congressional_districts": ";".join(
                        sorted(chambers["congressional"])
                    ),
                }
            )
            continue
        accepted.append(
            {
                "year": year,
                "county": county,
                "raw_precinct": raw,
                "group_id": group_id,
                "strategy": strategy,
            }
        )
    return pd.DataFrame(accepted), unresolved


def load_baf(path: Path, district_column: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        members = [
            item for item in archive.infolist() if item.filename.lower().endswith(".csv")
        ]
        if not members:
            raise RuntimeError(f"No CSV in historical plan archive: {path}")
        with archive.open(members[0]) as raw, TextIOWrapper(
            raw, encoding="utf-8-sig", errors="replace", newline=""
        ) as text:
            rows: list[tuple[str, str]] = []
            for row in csv.reader(text):
                if len(row) < 2:
                    continue
                geoid_match = re.search(r"(\d{15})", str(row[0]))
                geoid = geoid_match.group(1) if geoid_match else ""
                district = clean_district(row[1])
                if len(geoid) == 15 and geoid.startswith("37") and district:
                    rows.append((geoid, district))
    frame = pd.DataFrame(rows, columns=["blk2000ge", district_column]).drop_duplicates()
    conflicts = frame.groupby("blk2000ge")[district_column].nunique()
    if (conflicts > 1).any():
        raise RuntimeError(f"Conflicting block assignments in {path}")
    return frame.drop_duplicates("blk2000ge")


def load_plan_blocks(source_root: Path, year: int, vap: pd.DataFrame) -> pd.DataFrame:
    plans = PLAN_ARCHIVES[year]
    root = source_root / "ncga/block_assignments"
    output = vap[["blk2000ge", "county_fips_2000"]].drop_duplicates().copy()
    for chamber, filename in plans.items():
        output = output.merge(
            load_baf(root / filename, f"plan_{chamber}"),
            on="blk2000ge",
            how="left",
        )
    return output.fillna("")


def load_voter_history_codes(source_root: Path, year: int) -> set[tuple[str, str]]:
    path = source_root / "ncsbe/voter_history" / {
        2002: "history_stats_20021105.zip",
        2004: "history_stats_20041102.zip",
    }[year]
    codes: set[tuple[str, str]] = set()
    with zipfile.ZipFile(path) as archive:
        member = next(
            item
            for item in archive.infolist()
            if item.filename.lower().endswith(".txt")
        )
        with archive.open(member) as raw, TextIOWrapper(
            raw, encoding="utf-8-sig", errors="replace", newline=""
        ) as text:
            reader = csv.reader(text, delimiter="\t" if year == 2002 else ",")
            for index, row in enumerate(reader):
                if len(row) < 2:
                    continue
                if index == 0 and norm(row[0]) in {"COUNTY", "COUNTY_DESC"}:
                    continue
                county = norm(row[0])
                token = code_norm(row[1])
                if county and token:
                    codes.add((county, token))
    return codes


def add_synthetic_keys(rows: pd.DataFrame) -> pd.DataFrame:
    rows = rows.sort_values(["year", "county", "raw_precinct"]).copy()
    # These raw historical keys already exist on the vintage match map. Keep
    # identity stable and replace only the district-weight lookup behind them.
    rows["synthetic_key"] = (
        rows["county"].map(norm) + " - " + rows["raw_precinct"].map(norm)
    )
    return rows


def make_block_groups(
    vap: pd.DataFrame, year: int, plan_blocks: pd.DataFrame | None = None
) -> pd.DataFrame:
    county = vap["county_fips_2000"].map(NC_COUNTY_FIPS)
    if year == 2000:
        house = vap["sldl_2000"].map(clean_district)
        senate = vap["sldu_2000"].map(clean_district)
        cd = vap["cd106_2000"].map(clean_district)
        vtd = vap["vtd_code_2000"].map(code_norm)
        frames = []
        for signature, suffix in (
            ("HSC", "H" + house + "|S" + senate + "|C" + cd),
            ("SC", "S" + senate + "|C" + cd),
            ("HC", "H" + house + "|C" + cd),
            ("C", "C" + cd),
        ):
            for prefix in (county + "|", county + "|VTD" + vtd + "|"):
                frames.append(
                    pd.DataFrame(
                        {
                            "blk2000ge": vap["blk2000ge"],
                            "precinct_id": prefix + signature + "|" + suffix,
                            "cell_signature": signature,
                        }
                    )
                )
        return pd.concat(frames, ignore_index=True)
    vtd = pd.DataFrame(
        {
            "blk2000ge": vap["blk2000ge"],
            "precinct_id": county + "|VTD" + vap["vtd_code_2000"].map(code_norm),
        }
    )
    if plan_blocks is None:
        return vtd
    plan = plan_blocks.copy()
    plan_county = plan["county_fips_2000"].map(NC_COUNTY_FIPS)
    house = plan["plan_house"].map(clean_district)
    senate = plan["plan_senate"].map(clean_district)
    cd = plan["plan_congressional"].map(clean_district)
    frames = [vtd]
    specs = (
        ("PLANHSC", "H" + house + "|S" + senate + "|C" + cd, house.ne("") & senate.ne("") & cd.ne("")),
        ("PLANHS", "H" + house + "|S" + senate, house.ne("") & senate.ne("")),
        ("PLANHC", "H" + house + "|C" + cd, house.ne("") & cd.ne("")),
        ("PLANSC", "S" + senate + "|C" + cd, senate.ne("") & cd.ne("")),
    )
    for signature, suffix, valid in specs:
        frames.append(
            pd.DataFrame(
                {
                    "blk2000ge": plan.loc[valid, "blk2000ge"],
                    "precinct_id": (
                        plan_county.loc[valid] + f"|{signature}|" + suffix.loc[valid]
                    ),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def expand_groups(
    entries: dict[str, list[dict[str, object]]],
    detail: pd.DataFrame,
    mappings: pd.DataFrame,
) -> tuple[dict[str, list[dict[str, object]]], pd.DataFrame]:
    group_to_keys = mappings.groupby("group_id")["synthetic_key"].apply(list).to_dict()
    output: dict[str, list[dict[str, object]]] = {}
    for group_id, values in entries.items():
        for key in group_to_keys.get(group_id, []):
            output[key] = copy.deepcopy(values)
    detail = detail.rename(columns={"precinct_id": "group_id"}).merge(
        mappings[["group_id", "synthetic_key"]],
        on="group_id",
        how="inner",
    )
    return output, detail.rename(columns={"synthetic_key": "precinct_id"}).drop(
        columns=["group_id"]
    )


def write_overrides(
    production_path: Path,
    mappings: pd.DataFrame,
    out_path: Path,
    lineage_aliases: list[dict[str, str]],
    retained_sbe2006: list[dict[str, str]],
) -> None:
    with production_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        production = list(reader)
        fields = list(reader.fieldnames or [])
    if "experiment_note" not in fields:
        fields.append("experiment_note")
    replaced = {
        (str(row.year), norm(f"{row.county} - {row.raw_precinct}"))
        for row in mappings.itertuples()
    }
    replaced.update(
        (row["year"], norm(f"{row['county']} - {row['raw_precinct']}"))
        for row in lineage_aliases
    )
    replaced.update(
        (str(row["year"]), norm(f"{row['county']} - {row['raw_precinct']}"))
        for row in retained_sbe2006
    )
    rows = [
        {field: str(row.get(field) or "") for field in fields}
        for row in production
        if (str(row.get("year") or ""), norm(row.get("raw_precinct_key"))) not in replaced
    ]
    for row in mappings.itertuples():
        item = {field: "" for field in fields}
        item.update(
            {
                "year": str(row.year),
                "raw_precinct_key": f"{row.county} - {row.raw_precinct}",
                "canonical_precinct_key": row.synthetic_key,
                "experiment_note": f"staging-only {row.strategy} SF1 historical pilot",
            }
        )
        rows.append(item)
    for alias in lineage_aliases:
        item = {field: "" for field in fields}
        item.update(
            {
                "year": alias["year"],
                "raw_precinct_key": f"{alias['county']} - {alias['raw_precinct']}",
                "canonical_precinct_key": alias["canonical_precinct_key"],
                "experiment_note": (
                    "staging-only SBE2006 lineage alias; " + alias["evidence"]
                ),
            }
        )
        rows.append(item)
    for alias in retained_sbe2006:
        item = {field: "" for field in fields}
        item.update(
            {
                "year": str(alias["year"]),
                "raw_precinct_key": f"{alias['county']} - {alias['raw_precinct']}",
                "canonical_precinct_key": alias["canonical_precinct_key"],
                "experiment_note": (
                    "staging-only exact SBE2006 geometry; "
                    + str(alias.get("reason") or "unique county-year alias")
                ),
            }
        )
        rows.append(item)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    target_counties, _ = load_alias_evidence(args.aliases_csv)
    alias_canonical = load_alias_canonical_map(args.aliases_csv)
    all_counties = set().union(*(target_counties[year] for year in YEARS))
    name_to_fips = {name: fips for fips, name in NC_COUNTY_FIPS.items()}
    target_fips = {name_to_fips[name] for name in all_counties}

    vap = pd.read_csv(args.sf1_csv, dtype=str).fillna("")
    vap = vap[vap["county_fips_2000"].isin(target_fips)].copy()
    vap["blk2000ge"] = clean_geoid(vap["block_geoid00"])
    vap["vap_count_2000"] = pd.to_numeric(
        vap["vap_count_2000"], errors="coerce"
    ).fillna(0.0)
    bridge = load_fractional_bridge(args.nhgis_00_10, args.nhgis_10_20, target_fips)
    sf_vtds = {
        (NC_COUNTY_FIPS.get(row.county_fips_2000, ""), code_norm(row.vtd_code_2000))
        for row in vap.itertuples()
        if code_norm(row.vtd_code_2000)
    }

    plan_blocks = {
        year: load_plan_blocks(args.historical_source_root, year, vap)
        for year in (2002, 2004)
    }
    history_codes = {
        year: load_voter_history_codes(args.historical_source_root, year)
        for year in (2002, 2004)
    }

    mapping_parts = [
        collect_2000_precincts(
            RESULTS[2000], target_counties[2000], sf_vtds
        )
    ]
    direct_rejected: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    rescue_parts: list[pd.DataFrame] = []
    retained_sbe2006: list[dict[str, str]] = []
    for year in (2002, 2004):
        accepted, failed = collect_direct_precincts(
            year, RESULTS[year], target_counties[year], sf_vtds
        )
        plan_cell_candidates: list[dict[str, str]] = []
        for row in failed:
            token = code_norm(prefix_token(row["raw_precinct"]))
            canonical = alias_canonical.get((year, row["county"], token), set())
            if (year, row["county"]) in PREFER_EXACT_SBE2006_GEOMETRY and len(canonical) == 1:
                retained_sbe2006.append(
                    {
                        **row,
                        "canonical_precinct_key": next(iter(canonical)),
                        "strategy": "retained_exact_sbe2006_geometry",
                        "reason": "unique_2004_buncombe_precinct_alias",
                    }
                )
            else:
                plan_cell_candidates.append(row)
        rescued, unresolved = collect_plan_cell_precincts(
            year, RESULTS[year], plan_cell_candidates
        )
        mapping_parts.append(accepted)
        if not rescued.empty:
            mapping_parts.append(rescued)
            rescue_parts.append(rescued)
        direct_rejected.extend(failed)
        rejected.extend(unresolved)
    lineage_keys = {
        (row["year"], row["county"], row["raw_precinct"])
        for row in SBE2006_LINEAGE_ALIASES
    }
    rejected = [
        row
        for row in rejected
        if (row["year"], row["county"], row["raw_precinct"]) not in lineage_keys
    ]
    still_rejected: list[dict[str, str]] = []
    for row in rejected:
        token = code_norm(prefix_token(row["raw_precinct"]))
        canonical = alias_canonical.get((int(row["year"]), row["county"], token), set())
        if len(canonical) == 1:
            retained_sbe2006.append(
                {
                    **row,
                    "canonical_precinct_key": next(iter(canonical)),
                    "strategy": "retained_exact_sbe2006_geometry",
                }
            )
        else:
            still_rejected.append(row)
    rejected = still_rejected
    mappings = add_synthetic_keys(pd.concat(mapping_parts, ignore_index=True))
    mappings["voter_history_code_confirmed"] = mappings.apply(
        lambda row: (
            (row["county"], code_norm(prefix_token(row["raw_precinct"])))
            in history_codes.get(int(row["year"]), set())
        ),
        axis=1,
    )
    overrides_path = args.out_dir / "precinct_key_overrides.csv"
    write_overrides(
        args.production_overrides_csv,
        mappings,
        overrides_path,
        SBE2006_LINEAGE_ALIASES,
        retained_sbe2006,
    )

    base = json.loads(args.base_weights_json.read_text(encoding="utf-8"))
    validation: dict[str, Any] = {
        "schema": "urban_sf1_historical_legislative_weights.v1",
        "production_modified": False,
        "urban_counties_by_year": {
            str(year): sorted(target_counties[year]) for year in YEARS
        },
        "accepted_precincts_by_year": {
            str(year): int((mappings["year"] == year).sum()) for year in YEARS
        },
        "effective_geographic_linkages_by_year": {
            str(year): (
                int((mappings["year"] == year).sum())
                + sum(int(row["year"]) == year for row in retained_sbe2006)
                + sum(
                    int(row["year"]) == year for row in SBE2006_LINEAGE_ALIASES
                )
            )
            for year in YEARS
        },
        "rejected_direct_vtd_precincts": len(direct_rejected),
        "rescued_historical_plan_cell_precincts": sum(
            len(part) for part in rescue_parts
        ),
        "rescued_sbe2006_lineage_aliases": len(SBE2006_LINEAGE_ALIASES),
        "retained_exact_sbe2006_geometry_precincts": len(retained_sbe2006),
        "remaining_rejected_precincts": len(rejected),
        "years": {},
    }
    comparison_parts: list[pd.DataFrame] = []
    for year in YEARS:
        year_map = mappings[mappings["year"] == year].copy()
        groups = make_block_groups(vap, year, plan_blocks.get(year))
        flow = bridge.merge(groups, on="blk2000ge", how="inner").merge(
            vap[["blk2000ge", "vap_count_2000"]], on="blk2000ge", how="left"
        )
        output = copy.deepcopy(base)
        scope_counts: dict[str, int] = {}
        for scope_name, assignment_path, prefix, width, template in SCOPE_CONFIG:
            cell_entries, detail = scope_entries(
                flow,
                load_assignment(assignment_path),
                prefix=prefix,
                width=width,
                name_template=template,
            )
            if year == 2000:
                precise = year_map[year_map["group_id"].isin(cell_entries)].copy()
                fallback = year_map[
                    ~year_map["synthetic_key"].isin(precise["synthetic_key"])
                ].copy()
                fallback["group_id"] = fallback["fallback_group_id"]
                precise_entries, precise_detail = expand_groups(
                    cell_entries, detail, precise
                )
                fallback_entries, fallback_detail = expand_groups(
                    cell_entries, detail, fallback
                )
                entries = {**fallback_entries, **precise_entries}
                detail = pd.concat(
                    [precise_detail, fallback_detail], ignore_index=True
                )
            else:
                entries, detail = expand_groups(cell_entries, detail, year_map)
            precincts = dict(output["scopes"][scope_name]["precincts"])
            if year == 2000:
                # Exact VTD+historical-cell matches take precedence. Precincts
                # without that intersection use the evidence-backed historical
                # cell rather than an unrelated later-vintage precinct geometry.
                precincts = {
                    key: value
                    for key, value in precincts.items()
                    if key.split(" - ", 1)[0] not in target_counties[year]
                }
            else:
                # For direct-VTD years, remove only canonical SBE keys backed by
                # an accepted raw prefix. Rejected prefixes retain base weights.
                remove_keys: set[str] = set()
                for row in year_map.itertuples():
                    token = code_norm(prefix_token(row.raw_precinct))
                    remove_keys.update(
                        alias_canonical.get((year, row.county, token), set())
                    )
                precincts = {
                    key: value for key, value in precincts.items() if norm(key) not in remove_keys
                }
            precincts.update(entries)
            output["scopes"][scope_name]["precincts"] = dict(sorted(precincts.items()))
            output["scopes"][scope_name]["urban_sf1_weight_source"] = (
                "exact_vtd_historical_cell_plus_cell_fallback"
                if year == 2000
                else "direct_sf1_vtd_plus_historical_plan_cell"
            )
            scope_counts[scope_name] = len(entries)
            comparison_parts.append(
                detail.assign(year=year, scope=scope_name)[
                    ["year", "scope", "precinct_id", "district", "share", "mass", "block_count"]
                ]
            )
        output["historical_urban_sf1_pilot"] = {
            "year": year,
            "strategy": (
                "exact_vtd_historical_cell_plus_cell_fallback"
                if year == 2000
                else "direct_sf1_vtd_plus_historical_plan_cell"
            ),
            "counties": sorted(target_counties[year]),
            "accepted_precincts": int(len(year_map)),
            "production_safe": False,
        }
        out_json = args.out_dir / f"district_weights_{year}.json"
        out_json.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        validation["years"][str(year)] = {
            "strategy": output["historical_urban_sf1_pilot"]["strategy"],
            "accepted_precincts": int(len(year_map)),
            "counties_with_accepted_precincts": sorted(set(year_map["county"])),
            "scope_entry_counts": scope_counts,
            "weights_json": str(out_json.relative_to(ROOT)).replace("\\", "/"),
        }

    mappings.to_csv(args.out_dir / "precinct_linkage.csv", index=False)
    if rescue_parts:
        pd.concat(rescue_parts, ignore_index=True).to_csv(
            args.out_dir / "historical_plan_cell_rescues.csv", index=False
        )
    pd.DataFrame(SBE2006_LINEAGE_ALIASES).to_csv(
        args.out_dir / "sbe2006_lineage_aliases.csv", index=False
    )
    pd.DataFrame(retained_sbe2006).to_csv(
        args.out_dir / "retained_exact_sbe2006_geometry.csv", index=False
    )
    pd.DataFrame(rejected).to_csv(args.out_dir / "rejected_direct_vtd.csv", index=False)
    pd.concat(comparison_parts, ignore_index=True).to_csv(
        args.out_dir / "weight_detail.csv", index=False
    )
    validation["overrides_csv"] = str(overrides_path.relative_to(ROOT)).replace("\\", "/")
    validation["production_safe"] = False
    validation["production_safe_reason"] = (
        "Staging pilot; direct VTD and historical-plan cell coverage and resulting "
        "urban district margins still require validation."
    )
    summary_path = args.out_dir / "summary.json"
    summary_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2))
    print(f"Wrote {args.out_dir}")


if __name__ == "__main__":
    main()
