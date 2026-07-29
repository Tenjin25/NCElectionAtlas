#!/usr/bin/env python3
"""Build a separate historical-legislature explorer on modern NCGA lines.

This intentionally does not write to ``data/district_contests*``.  Historical
House and Senate races are different contests with different candidates, and
often include uncontested territory.  The output is therefore a party-vote
composite with explicit coverage and source-district lineage, not a claim that
the historical candidates ran against one another in a modern district.

The early-year path reuses the audited Census 2000 / official historical-plan
weights already checked into ``data/reports/urban_sf1_historical``.  The 2006
and 2008 path uses the SBE 2006 bridge.  The 2010 path derives equivalent
precinct weights from the SBE 2012-era block bridge.

Examples:
  python scripts/build_legislative_history_crosswalks.py
  python scripts/build_legislative_history_crosswalks.py --years 2000,2004,2008
  python scripts/build_legislative_history_crosswalks.py --line-years 2024
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_district_contests_from_batch_shatter import (  # noqa: E402
    _compact_token,
    _norm_spaces,
    apply_candidate_party_overrides,
    build_auto_precinct_overrides,
    build_sbe2006_weight_alias_lookup,
    build_precinct_party_votes,
    calculate_competitiveness,
    canonicalize_candidate_label,
    clean_precinct_name,
    load_crosswalk,
    load_district_map,
    load_precinct_overrides,
    load_sbe_precinct_code_map,
    load_vap,
    party_group,
    resolve_vintage_match_crosswalk,
    sbe2006_precinct_key_aliases,
)


DEFAULT_YEARS = tuple(range(2000, 2021, 2))
DEFAULT_LINE_YEARS = (2022, 2024)
NCGA_REDISTRICTING_URL = "https://www.ncleg.gov/Redistricting"

CHAMBERS = {
    "state_house": {
        "label": "State House",
        "short": "HD",
        "district_count": 120,
        "patterns": (
            re.compile(r"^HOUSE\s+DISTRICT\s+0*(\d+)$", re.I),
            re.compile(r"^NC\s+HOUSE\s*\(\s*0*(\d+)\s*\)$", re.I),
            re.compile(r"^NC\s+STATE\s+HOUSE\s+DISTRICT\s+0*(\d+)$", re.I),
            re.compile(
                r"^NC\s+HOUSE\s+OF\s+REPRESENTATIVES\s+DISTRICT\s+0*(\d+)$",
                re.I,
            ),
        ),
    },
    "state_senate": {
        "label": "State Senate",
        "short": "SD",
        "district_count": 50,
        "patterns": (
            re.compile(r"^SENATE\s+DISTRICT\s+0*(\d+)$", re.I),
            re.compile(r"^NC\s+SENATE\s*\(\s*0*(\d+)\s*\)$", re.I),
            re.compile(r"^NC\s+STATE\s+SENATE\s+DISTRICT\s+0*(\d+)$", re.I),
        ),
    },
}

SOURCE_PLANS = {
    2000: {
        "state_house": ("1992 House Base Plan 5", "House_1992"),
        "state_senate": ("1992 Senate Base Plan 6", "Senate_1992"),
    },
    2002: {
        "state_house": ("Court-Ordered 2002 House Plan", "House_2002_Court"),
        "state_senate": ("Court-Ordered 2002 Senate Plan", "Senate_2002_Court"),
    },
    2004: {
        "state_house": ("2003 House Redistricting Plan", "House_2003"),
        "state_senate": ("2003 Senate Redistricting Plan", "Senate_2003"),
    },
    2006: {
        "state_house": ("2003 House Redistricting Plan", "House_2003"),
        "state_senate": ("2003 Senate Redistricting Plan", "Senate_2003"),
    },
    2008: {
        "state_house": ("2003 House Redistricting Plan", "House_2003"),
        "state_senate": ("2003 Senate Redistricting Plan", "Senate_2003"),
    },
    2010: {
        "state_house": ("2009 House Redistricting Plan", "House_2009"),
        "state_senate": ("2003 Senate Redistricting Plan", "Senate_2003"),
    },
    2012: {
        "state_house": ("Lewis-Dollar-Dockham 4", "House_2011"),
        "state_senate": ("Rucho Senate 2", "Senate_2011"),
    },
    2014: {
        "state_house": ("Lewis-Dollar-Dockham 4", "House_2011"),
        "state_senate": ("Rucho Senate 2", "Senate_2011"),
    },
    2016: {
        "state_house": ("Lewis-Dollar-Dockham 4", "House_2011"),
        "state_senate": ("Rucho Senate 2", "Senate_2011"),
    },
    2018: {
        "state_house": ("Court-Ordered 2018 House Plan", "House_2018_Court"),
        "state_senate": ("Court-Ordered 2018 Senate Plan", "Senate_2018_Court"),
    },
    2020: {
        "state_house": ("2019 House Remedial Map", "House_2019"),
        "state_senate": ("2019 Senate Consensus Nonpartisan Map", "Senate_2019"),
    },
}

SOURCE_PLAN_URL_OVERRIDES = {
    (2018, "state_house"): "https://www.ncleg.gov/Files/GIS/Plans_Main/House_2018_Court/House%2018%20USSupCt%20-%20BlockFile.zip",
    (2018, "state_senate"): "https://www.ncleg.gov/Files/GIS/Plans_Main/Senate_2018_Court/Senate%2018%20USSupCt%20-%20BlockFile.zip",
    (2020, "state_house"): "https://www.ncleg.gov/Files/GIS/Plans_Main/House_2019/HB%201020%20H%20Red%20Comm%20CSBK-25_Blockfile.zip",
    (2020, "state_senate"): "https://www.ncleg.gov/Files/GIS/Plans_Main/Senate_2019/Senate%20Consensus%20Nonpartisan%20Map%20v3_BlockFile.zip",
}

TARGET_MAPS = {
    2022: {
        "state_house": ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv",
        "state_senate": ROOT / "data/tmp/block_assign_extract/SL 2022-2.csv",
    },
    2024: {
        "state_house": ROOT / "data/tmp/block_assign_extract_2024/SL_2024_4.csv",
        "state_senate": ROOT / "data/tmp/block_assign_extract_2024/SL_2024_2.csv",
    },
}

# District magnitude under the final pre-2002 plans. These values sum to the
# constitutional 120 House and 50 Senate seats while retaining the old district
# numbers printed on the 2000 ballot.
MULTI_MEMBER_MAGNITUDES_2000 = {
    "state_house": {
        4: 2, 14: 2, 17: 2, 18: 2, 19: 2, 22: 2, 23: 3, 24: 2, 25: 3,
        40: 3, 41: 2, 45: 2, 46: 2, 48: 3, 51: 3, 52: 2, 89: 2,
    },
    "state_senate": {
        12: 2, 13: 2, 14: 2, 16: 2, 17: 2, 20: 2, 27: 2, 28: 2,
    },
}
BLOCK_BRIDGE_BASE_CACHE: dict[int, tuple[pd.DataFrame, Path]] = {}
TARGET_DISTRICT_MAP_CACHE: dict[tuple[int, str], pd.DataFrame] = {}

LEGISLATIVE_CANDIDATE_DISPLAY_OVERRIDES = {
    # The SBE ballot export includes her nickname in the middle of the name.
    # Use the public display name while leaving the source CSV untouched.
    "ERNESTINE (BYRD) BAZEMORE": "Ernestine Bazemore",
}


def parse_int_list(raw: str) -> list[int]:
    return sorted({int(part.strip()) for part in str(raw).split(",") if part.strip()})


def legislative_candidate_display_name(name: str) -> str:
    normalized = re.sub(r"\s+", " ", str(name or "")).strip()
    normalized = re.sub(
        r"\s+\(\s*replacement\s+for\s+[^)]+\)\s*$",
        "",
        normalized,
        flags=re.I,
    ).strip()
    normalized = canonicalize_candidate_label(normalized)
    key = re.sub(r"\s+", " ", normalized).strip().upper()
    return LEGISLATIVE_CANDIDATE_DISPLAY_OVERRIDES.get(key, normalized)


def is_generic_candidate_placeholder(name: str) -> bool:
    key = re.sub(r"[^A-Z]+", " ", str(name or "").upper()).strip()
    return key in {"WRITE IN", "WRITE IN MISCELLANEOUS"}


def discover_general_csv(year: int) -> Path:
    candidates = sorted((ROOT / "data" / str(year)).glob(f"{year}11*__nc__general__precinct.csv"))
    if not candidates:
        candidates = sorted((ROOT / "data" / str(year)).glob("*__nc__general__precinct.csv"))
    if not candidates:
        raise FileNotFoundError(f"No general-election precinct CSV found for {year}")
    return max(candidates, key=lambda path: path.stat().st_size)


def source_district(office: str, chamber: str) -> int | None:
    normalized = re.sub(r"\s+", " ", str(office or "").strip())
    for pattern in CHAMBERS[chamber]["patterns"]:
        match = pattern.match(normalized)
        if match:
            return int(match.group(1))
    return None


def candidate_slate(
    office_rows: pd.DataFrame,
    *,
    year: int,
    seats: int,
) -> list[dict[str, Any]]:
    """Return every candidate separately, preserving multi-member ballot slates."""
    frame = office_rows.copy()
    frame["votes_num"] = pd.to_numeric(frame["votes"], errors="coerce").fillna(0.0)
    frame["party_group"] = frame["party"].map(party_group)
    frame = apply_candidate_party_overrides(frame, election_year=year)
    frame["candidate"] = frame["candidate"].map(legislative_candidate_display_name)
    frame = frame[frame["candidate"].astype(str).str.strip().ne("")]
    frame = frame[~frame["candidate"].map(is_generic_candidate_placeholder)]
    grouped = (
        frame.groupby(["candidate", "party_group"], as_index=False)["votes_num"]
        .sum()
        .sort_values(["votes_num", "candidate"], ascending=[False, True])
        .reset_index(drop=True)
    )
    party_labels = {"dem_votes": "DEM", "rep_votes": "REP", "other_votes": "OTHER"}
    return [
        {
            "name": str(row.candidate),
            "party": party_labels.get(str(row.party_group), "OTHER"),
            "votes": int(round(float(row.votes_num))),
            "rank": rank,
            "elected": rank <= seats,
        }
        for rank, row in enumerate(grouped.itertuples(index=False), start=1)
    ]


def official_plan_metadata(year: int, chamber: str) -> dict[str, str]:
    label, directory = SOURCE_PLANS[year][chamber]
    return {
        "label": label,
        "directory": directory,
        "block_assignment_url": SOURCE_PLAN_URL_OVERRIDES.get(
            (year, chamber),
            f"https://www.ncleg.gov/Files/GIS/Plans_Main/{directory}/baf.zip",
        ),
        "archive_page": NCGA_REDISTRICTING_URL,
    }


def select_scope(payload: dict, line_year: int, chamber: str) -> dict:
    scope_name = ((payload.get("scope_sets") or {}).get(str(line_year)) or {}).get(chamber)
    scope = (payload.get("scopes") or {}).get(scope_name or "")
    if not isinstance(scope, dict) or not scope.get("precincts"):
        raise KeyError(f"Missing {line_year} {chamber} scope in weight payload")
    return scope


def build_block_bridge_scope(year: int, line_year: int, chamber: str) -> dict:
    """Build modern-district weights from the closest available SBE precinct vintage."""
    if year not in BLOCK_BRIDGE_BASE_CACHE:
        crosswalk_path = resolve_vintage_match_crosswalk(year)
        vap_path = ROOT / "data/census/block_vap_2020_nc.csv"
        crosswalk = load_crosswalk(crosswalk_path, "precinct_id", "block_geoid20")
        vap = load_vap(vap_path, "block_geoid20", "vap_count")
        base = crosswalk[["block_geoid20", "precinct_id"]].merge(
            vap[["block_geoid20", "vap_count"]], on="block_geoid20", how="left"
        )
        BLOCK_BRIDGE_BASE_CACHE[year] = (base, crosswalk_path)
    base, crosswalk_path = BLOCK_BRIDGE_BASE_CACHE[year]
    target_path = TARGET_MAPS[line_year][chamber]
    target_key = (line_year, chamber)
    if target_key not in TARGET_DISTRICT_MAP_CACHE:
        TARGET_DISTRICT_MAP_CACHE[target_key] = load_district_map(
            target_path, "Block", "District"
        )
    target = TARGET_DISTRICT_MAP_CACHE[target_key]
    merged = (
        base
        .merge(target[["block_geoid20", "district"]], on="block_geoid20", how="inner")
    )
    merged["vap_count"] = pd.to_numeric(merged["vap_count"], errors="coerce").fillna(0.0)
    grouped = (
        merged.groupby(["precinct_id", "district"], as_index=False)
        .agg(vap_count=("vap_count", "sum"), block_count=("block_geoid20", "nunique"))
    )
    totals = (
        grouped.groupby("precinct_id", as_index=False)["vap_count"]
        .sum()
        .rename(columns={"vap_count": "precinct_vap"})
    )
    grouped = grouped.merge(totals, on="precinct_id", how="left")
    block_totals = (
        grouped.groupby("precinct_id", as_index=False)["block_count"]
        .sum()
        .rename(columns={"block_count": "precinct_blocks"})
    )
    grouped = grouped.merge(block_totals, on="precinct_id", how="left")
    grouped["share"] = grouped["vap_count"] / grouped["precinct_vap"].replace(0, pd.NA)
    zero_vap = grouped["share"].isna()
    grouped.loc[zero_vap, "share"] = (
        grouped.loc[zero_vap, "block_count"]
        / grouped.loc[zero_vap, "precinct_blocks"].replace(0, pd.NA)
    )
    grouped["share"] = pd.to_numeric(grouped["share"], errors="coerce").fillna(0.0)

    precincts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in grouped.itertuples(index=False):
        precincts[str(row.precinct_id).strip().upper()].append(
            {
                "district": str(row.district).lstrip("0") or "0",
                "share": float(row.share),
                "vap_count": float(row.vap_count),
                "block_count": int(row.block_count),
                "weight_source": "vap" if float(row.precinct_vap) > 0 else "blocks",
            }
        )
    return {
        "scope": f"{line_year}_{chamber}",
        "target_year": line_year,
        "district_type": chamber,
        "plan_id": f"{line_year}_{chamber}",
        "source_crosswalk": (
            str(crosswalk_path.relative_to(ROOT)).replace("\\", "/")
            if crosswalk_path.is_absolute()
            else str(crosswalk_path).replace("\\", "/")
        ),
        "assignment_path": str(target_path.relative_to(ROOT)).replace("\\", "/"),
        "precincts": dict(precincts),
    }


def load_scope_weights(year: int, line_year: int, chamber: str) -> tuple[dict, str]:
    if year in (2000, 2002, 2004):
        path = ROOT / f"data/reports/urban_sf1_historical/district_weights_{year}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return select_scope(payload, line_year, chamber), str(path.relative_to(ROOT)).replace("\\", "/")
    if year in (2006, 2008):
        path = ROOT / "data/mappings/sbe2006_to_modern_district_weights.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return select_scope(payload, line_year, chamber), str(path.relative_to(ROOT)).replace("\\", "/")
    if year >= 2010:
        scope = build_block_bridge_scope(year, line_year, chamber)
        return scope, f"derived:{scope.get('source_crosswalk', '')}"
    raise ValueError(f"Unsupported legislative-history year: {year}")


def add_maps(target: defaultdict[str, float], source: dict[str, int]) -> None:
    for district, votes in source.items():
        target[str(int(district))] += float(votes)


def sum_party_maps(dem: dict[str, int], rep: dict[str, int], other: dict[str, int]) -> dict[str, int]:
    keys = set(dem) | set(rep) | set(other)
    return {
        str(int(key)): int(dem.get(key, 0)) + int(rep.get(key, 0)) + int(other.get(key, 0))
        for key in keys
    }


def coverage_grade(value: float) -> str:
    if value >= 75:
        return "high"
    if value >= 50:
        return "medium"
    if value > 0:
        return "low"
    return "none"


def make_scope_allocator(scope_weights: dict):
    """Return a cached precinct allocator compatible with the audited weight schema."""
    precincts = {
        str(key).strip().upper(): entries
        for key, entries in (scope_weights.get("precincts") or {}).items()
        if isinstance(entries, list)
    }
    matched_ids = set(precincts)
    alias_lookup = build_sbe2006_weight_alias_lookup(matched_ids)
    resolve_cache: dict[str, str | None] = {}
    county_district_mass: dict[str, defaultdict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    for precinct_id, entries in precincts.items():
        county = precinct_id.split(" - ", 1)[0].strip().upper()
        for entry in entries:
            district = str((entry or {}).get("district", "")).strip().lstrip("0") or "0"
            mass = float((entry or {}).get("vap_count") or 0.0)
            if mass <= 0:
                mass = float((entry or {}).get("share") or 0.0)
            if county and district and mass > 0:
                county_district_mass[county][district] += mass
    county_shares: dict[str, dict[str, float]] = {}
    for county, masses in county_district_mass.items():
        total_mass = sum(masses.values())
        if total_mass > 0:
            county_shares[county] = {
                district: mass / total_mass for district, mass in masses.items()
            }

    def resolve(raw: str) -> str | None:
        key = _norm_spaces(raw)
        if key in resolve_cache:
            return resolve_cache[key]
        hit: str | None = None
        for alias in sbe2006_precinct_key_aliases(key):
            if alias in precincts:
                hit = alias
                break
            hit = alias_lookup.get(alias) or alias_lookup.get(_compact_token(alias))
            if hit:
                break
        resolve_cache[key] = hit
        return hit

    def allocate(
        precinct_party: pd.DataFrame,
    ) -> tuple[dict[str, int], dict[str, int], dict[str, int], int, int]:
        rows = precinct_party.copy()
        rows["_resolved"] = rows["precinct_id"].astype(str).map(resolve)
        matched = int(rows["_resolved"].notna().sum())
        total = int(len(rows))
        outputs: dict[str, dict[str, int]] = {}
        for column in ("dem_votes", "rep_votes", "other_votes"):
            district_votes: defaultdict[str, float] = defaultdict(float)
            for row in rows[["precinct_id", "_resolved", column]].itertuples(
                index=False, name=None
            ):
                precinct_id, resolved, raw_votes = row
                numeric_votes = pd.to_numeric(raw_votes, errors="coerce")
                if pd.isna(numeric_votes):
                    continue
                votes = float(numeric_votes)
                if not votes:
                    continue
                if resolved:
                    for entry in precincts.get(str(resolved), []):
                        district = str((entry or {}).get("district", "")).strip().lstrip("0") or "0"
                        share = float((entry or {}).get("share") or 0.0)
                        if district and share > 0:
                            district_votes[district] += votes * share
                else:
                    county = str(precinct_id).split(" - ", 1)[0].strip().upper()
                    for district, share in county_shares.get(county, {}).items():
                        district_votes[district] += votes * share
            outputs[column] = {
                key: int(round(value))
                for key, value in district_votes.items()
                if abs(value) > 0
            }
        return (
            outputs["dem_votes"],
            outputs["rep_votes"],
            outputs["other_votes"],
            matched,
            total,
        )

    return allocate


def prepare_chamber_races(
    src: pd.DataFrame,
    *,
    year: int,
    chamber: str,
    precinct_overrides: dict[str, str],
) -> list[dict[str, Any]]:
    """Normalize and non-geographic-allocate every source race once per year."""
    prepared: list[dict[str, Any]] = []
    office_groups = {
        str(office): frame.copy()
        for office, frame in src.groupby("office", sort=False)
    }
    for office in sorted(office_groups):
        old_district = source_district(office, chamber)
        if old_district is None:
            continue
        seats = (
            MULTI_MEMBER_MAGNITUDES_2000.get(chamber, {}).get(old_district, 1)
            if year == 2000
            else 1
        )
        candidates = candidate_slate(
            office_groups[office],
            year=year,
            seats=seats,
        )
        precinct_party, dem_candidate, rep_candidate = build_precinct_party_votes(
            office_groups[office],
            office,
            precinct_overrides=precinct_overrides,
            election_year=year,
        )
        dem_candidate = legislative_candidate_display_name(dem_candidate)
        rep_candidate = legislative_candidate_display_name(rep_candidate)
        if precinct_party.empty:
            continue
        dem_total = int(round(float(precinct_party["dem_votes"].sum())))
        rep_total = int(round(float(precinct_party["rep_votes"].sum())))
        other_total = int(round(float(precinct_party["other_votes"].sum())))
        total_votes = dem_total + rep_total + other_total
        if total_votes <= 0:
            continue
        prepared.append(
            {
                "office": office,
                "old_district": old_district,
                "precinct_party": precinct_party,
                "dem_candidate": dem_candidate,
                "rep_candidate": rep_candidate,
                "candidates": candidates,
                "seats": seats,
                "dem_total": dem_total,
                "rep_total": rep_total,
                "other_total": other_total,
                "total_votes": total_votes,
                "contested": dem_total > 0 and rep_total > 0,
            }
        )
    return prepared


def build_chamber_year(
    prepared_races: list[dict[str, Any]],
    *,
    year: int,
    line_year: int,
    chamber: str,
    scope_weights: dict,
    weights_source: str,
) -> dict:
    composite_dem: defaultdict[str, float] = defaultdict(float)
    composite_rep: defaultdict[str, float] = defaultdict(float)
    composite_other: defaultdict[str, float] = defaultdict(float)
    allocated_all: defaultdict[str, float] = defaultdict(float)
    allocated_contested: defaultdict[str, float] = defaultdict(float)
    lineage: dict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
    source_races: list[dict[str, Any]] = []
    matched_rows = 0
    total_rows = 0
    allocate = make_scope_allocator(scope_weights)

    for race in prepared_races:
        office = str(race["office"])
        old_district = int(race["old_district"])
        precinct_party = race["precinct_party"]
        dem_candidate = str(race["dem_candidate"])
        rep_candidate = str(race["rep_candidate"])
        candidates = list(race.get("candidates") or [])
        seats = int(race.get("seats") or 1)
        dem_total = int(race["dem_total"])
        rep_total = int(race["rep_total"])
        other_total = int(race["other_total"])
        total_votes = int(race["total_votes"])
        contested = bool(race["contested"])
        dem_map, rep_map, other_map, matched, total = allocate(precinct_party)
        matched_rows += matched
        total_rows += total
        total_map = sum_party_maps(dem_map, rep_map, other_map)

        for modern_district, votes in total_map.items():
            allocated_all[modern_district] += votes
            lineage[modern_district][str(old_district)] += votes
            if contested:
                allocated_contested[modern_district] += votes
        if contested:
            add_maps(composite_dem, dem_map)
            add_maps(composite_rep, rep_map)
            add_maps(composite_other, other_map)

        if seats > 1:
            outcome = "MULTI_MEMBER_BALLOT"
        elif not contested:
            outcome = "UNCONTESTED"
        elif dem_total > rep_total:
            outcome = "DEM"
        elif rep_total > dem_total:
            outcome = "REP"
        else:
            outcome = "TIE"
        source_races.append(
            {
                "district": old_district,
                "office": office,
                "dem_candidate": dem_candidate,
                "rep_candidate": rep_candidate,
                "candidates": candidates,
                "seats": seats,
                "dem_votes": dem_total,
                "rep_votes": rep_total,
                "other_votes": other_total,
                "total_candidate_votes": total_votes,
                "contested": contested,
                "outcome": outcome,
            }
        )

    results: dict[str, dict[str, Any]] = {}
    source_race_by_district = {
        str(int(race["district"])): race
        for race in source_races
    }
    district_count = int(CHAMBERS[chamber]["district_count"])
    for district in range(1, district_count + 1):
        key = str(district)
        dem = int(round(composite_dem.get(key, 0.0)))
        rep = int(round(composite_rep.get(key, 0.0)))
        other = int(round(composite_other.get(key, 0.0)))
        total = dem + rep + other
        margin = rep - dem
        margin_pct = (margin / total * 100.0) if total else 0.0
        all_votes = float(allocated_all.get(key, 0.0))
        contested_votes = float(allocated_contested.get(key, 0.0))
        coverage = (contested_votes / all_votes * 100.0) if all_votes else 0.0
        source_total = sum(lineage[key].values())
        sources = []
        for old, votes in sorted(
            lineage[key].items(), key=lambda item: (-item[1], int(item[0]))
        )[:8]:
            source_race = source_race_by_district.get(str(int(old)), {})
            sources.append(
                {
                    "district": int(old),
                    "share_pct": round(
                        (votes / source_total * 100.0) if source_total else 0.0,
                        2,
                    ),
                    "allocated_candidate_votes": int(round(votes)),
                    "seats": int(source_race.get("seats") or 1),
                    "candidates": list(source_race.get("candidates") or []),
                }
            )
        winner = "REP" if margin > 0 else ("DEM" if margin < 0 else "TIE")
        results[key] = {
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": other,
            "total_votes": total,
            "dem_candidate": "Democratic legislative candidates",
            "rep_candidate": "Republican legislative candidates",
            "margin": margin,
            "margin_pct": round(margin_pct, 2),
            "winner": winner,
            "competitiveness": {"color": calculate_competitiveness(margin_pct)},
            "contested_vote_coverage_pct": round(coverage, 2),
            "coverage_grade": coverage_grade(coverage),
            "source_districts": sources,
        }

    statewide_dem = sum(int(row["dem_votes"]) for row in results.values())
    statewide_rep = sum(int(row["rep_votes"]) for row in results.values())
    statewide_other = sum(int(row["other_votes"]) for row in results.values())
    statewide_total = statewide_dem + statewide_rep + statewide_other
    plan = official_plan_metadata(year, chamber)
    contested_races = sum(bool(row["contested"]) for row in source_races)
    source_candidate_votes = sum(int(row["total_candidate_votes"]) for row in source_races)
    allocated_candidate_votes = int(round(sum(allocated_all.values())))
    contested_source_votes = sum(
        int(row["total_candidate_votes"]) for row in source_races if row["contested"]
    )
    return {
        "schema": "nc_legislative_history.v1",
        "year": year,
        "chamber": chamber,
        "target_lines_year": line_year,
        "title": f"{year} {CHAMBERS[chamber]['label']} vote on {line_year} lines",
        "meta": {
            "interpretation": "party_vote_composite_on_modern_geometry",
            "source_plan": plan,
            "weights_source": weights_source,
            "match_coverage_pct": round(
                (matched_rows / total_rows * 100.0) if total_rows else 0.0, 2
            ),
            "allocated_vote_coverage_pct": round(
                (allocated_candidate_votes / source_candidate_votes * 100.0)
                if source_candidate_votes
                else 0.0,
                2,
            ),
            "contested_vote_allocation_pct": round(
                (statewide_total / contested_source_votes * 100.0)
                if contested_source_votes
                else 0.0,
                2,
            ),
            "source_candidate_votes": source_candidate_votes,
            "allocated_candidate_votes": allocated_candidate_votes,
            "matched_precinct_rows": matched_rows,
            "total_precinct_rows": total_rows,
            "source_race_count": len(source_races),
            "contested_source_race_count": contested_races,
            "uncontested_source_race_count": len(source_races) - contested_races,
            "multi_member_ballot": year == 2000,
            "multi_member_district_magnitudes": (
                {
                    str(district): seats
                    for district, seats in MULTI_MEMBER_MAGNITUDES_2000[chamber].items()
                }
                if year == 2000
                else {}
            ),
            "warning": (
                "The 2000 plan included multi-member districts. Values are candidate-vote "
                "shares and are not comparable to single-member turnout."
                if year == 2000
                else "Modern-district values combine different historical races and exclude "
                "uncontested races from the partisan margin."
            ),
            "statewide_composite": {
                "dem_votes": statewide_dem,
                "rep_votes": statewide_rep,
                "other_votes": statewide_other,
                "total_votes": statewide_total,
            },
        },
        "general": {"results": results},
        "source_races": sorted(source_races, key=lambda row: (row["district"], row["office"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build separate historical NC House/Senate composites on modern lines."
    )
    parser.add_argument("--years", default=",".join(map(str, DEFAULT_YEARS)))
    parser.add_argument("--line-years", default=",".join(map(str, DEFAULT_LINE_YEARS)))
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "data/legislative_history"
    )
    args = parser.parse_args()
    years = parse_int_list(args.years)
    line_years = parse_int_list(args.line_years)
    unsupported = sorted(set(years) - set(DEFAULT_YEARS))
    if unsupported:
        raise ValueError(f"Unsupported years: {unsupported}")
    unsupported_lines = sorted(set(line_years) - set(TARGET_MAPS))
    if unsupported_lines:
        raise ValueError(f"Unsupported target line years: {unsupported_lines}")

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    scope_cache: dict[tuple[int, int, str], tuple[dict, str]] = {}
    for year in years:
        results_csv = discover_general_csv(year)
        print(f"[{year}] {results_csv.relative_to(ROOT)}")
        src = pd.read_csv(results_csv, dtype=str, low_memory=False).fillna("")
        sbe_shp = (
            ROOT / "data/Precincts2006Gen/Precincts2006Gen.shp"
            if year <= 2010
            else ROOT / "data/census/SBE_PRECINCTS_20131004/PRECINCTS_20131004.shp"
            if year <= 2014
            else ROOT / "data/census/SBE_PRECINCTS_20150918/PRECINCTS_20150918.shp"
            if year <= 2016
            else ROOT / "data/SBE_PRECINCTS_20170519/Precincts2.shp"
            if year <= 2018
            else Path()
        )
        sbe_map = {}
        if str(sbe_shp) not in {"", "."} and sbe_shp.exists():
            sbe_map = load_sbe_precinct_code_map(sbe_shp)
        clean_precinct_name._sbe_map = sbe_map  # type: ignore[attr-defined]
        build_auto_precinct_overrides._sbe_map = sbe_map  # type: ignore[attr-defined]
        reference_key = (year, line_years[0], "state_house")
        scope_cache[reference_key] = load_scope_weights(*reference_key)
        reference_scope = scope_cache[reference_key][0]
        matched_precincts = {
            str(key).strip().upper()
            for key in (reference_scope.get("precincts") or {})
        }
        source_precinct_ids = (
            src["county"].astype(str).str.strip().str.upper()
            + " - "
            + src["precinct"].astype(str).str.strip().str.upper()
        )
        auto_overrides = build_auto_precinct_overrides(
            source_precinct_ids, matched_precincts
        )
        manual_overrides = load_precinct_overrides(
            ROOT / "data/mappings/precinct_key_overrides.csv", year
        )
        precinct_overrides = {**auto_overrides, **manual_overrides}
        precinct_overrides = {
            raw: canonical
            for raw, canonical in precinct_overrides.items()
            if str(canonical).strip().upper() in matched_precincts
        }
        prepared_by_chamber = {
            chamber: prepare_chamber_races(
                src,
                year=year,
                chamber=chamber,
                precinct_overrides=precinct_overrides,
            )
            for chamber in CHAMBERS
        }
        for line_year in line_years:
            line_dir = out_dir / str(line_year)
            line_dir.mkdir(parents=True, exist_ok=True)
            for chamber in CHAMBERS:
                cache_key = (year, line_year, chamber)
                scope_cache[cache_key] = load_scope_weights(year, line_year, chamber)
                scope, weights_source = scope_cache[cache_key]
                payload = build_chamber_year(
                    prepared_by_chamber[chamber],
                    year=year,
                    line_year=line_year,
                    chamber=chamber,
                    scope_weights=scope,
                    weights_source=weights_source,
                )
                filename = f"{chamber}_{year}.json"
                output = line_dir / filename
                output.write_text(
                    json.dumps(payload, indent=2) + "\n",
                    encoding="utf-8",
                )
                manifest.append(
                    {
                        "year": year,
                        "chamber": chamber,
                        "target_lines_year": line_year,
                        "file": f"{line_year}/{filename}",
                        "districts": len(payload["general"]["results"]),
                        "source_races": payload["meta"]["source_race_count"],
                        "contested_source_races": payload["meta"][
                            "contested_source_race_count"
                        ],
                        "match_coverage_pct": payload["meta"]["match_coverage_pct"],
                    }
                )
                print(
                    f"  {line_year} {chamber}: {output.relative_to(ROOT)} "
                    f"({payload['meta']['contested_source_race_count']}/"
                    f"{payload['meta']['source_race_count']} contested)"
                )

    manifest.sort(
        key=lambda row: (row["target_lines_year"], row["year"], row["chamber"])
    )
    manifest_payload = {
        "schema": "nc_legislative_history_manifest.v1",
        "description": (
            "Historical NC House and Senate party-vote composites allocated to modern "
            "district lines. Kept separate from ordinary contest slices."
        ),
        "official_plan_archive": NCGA_REDISTRICTING_URL,
        "files": manifest,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {(out_dir / 'manifest.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
