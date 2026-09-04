#!/usr/bin/env python3
"""Build NCSBE and MGGG projections for modern NC Senate/Congress plans.

NCSBE is used for 2016+ statewide and judicial contests. MGGG supplies the
older statewide contests carried by its NC VTD package. Votes are allocated
from election-vintage precincts/VTDs to official 2020-block plan assignments
with 2020 voting-age-population weights.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from math import floor
from pathlib import Path
from typing import Any

import pandas as pd
import shapefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_district_contests_from_batch_shatter as district_builder  # noqa: E402
from shatter_precinct_votes_vap import load_crosswalk  # noqa: E402


PLAN_SPECS = {
    "2022_state_senate": {
        "scope": "state_senate",
        "lines": 2022,
        "plan_id": "SL 2022-2",
        "assignment": ROOT / "data/tmp/block_assign_extract/SL 2022-2.csv",
        "block_col": "Block",
        "district_col": "District",
        "live_dir": ROOT / "data/district_contests",
    },
    "2022_congressional": {
        "scope": "congressional",
        "lines": 2022,
        "plan_id": "2022 Interim Congressional (Court)",
        "assignment": ROOT / "data/tmp/block_assign_extract/NC_CD118.csv",
        "block_col": "GEOID",
        "district_col": "CDFP",
        "live_dir": ROOT / "data/district_contests",
    },
    "2024_state_senate": {
        "scope": "state_senate",
        "lines": 2024,
        "plan_id": "SL 2023-146",
        "assignment": ROOT / "data/tmp/block_assign_extract_2024/SL_2024_2.csv",
        "block_col": "Block",
        "district_col": "District",
        "live_dir": ROOT / "data/district_contests_2024_lines",
    },
    "2024_congressional": {
        "scope": "congressional",
        "lines": 2024,
        "plan_id": "SL 2023-145",
        "assignment": ROOT / "data/tmp/block_assign_extract_2024/NC_CD119.csv",
        "block_col": "GEOID",
        "district_col": "CDFP",
        "live_dir": ROOT / "data/district_contests_2024_lines",
    },
    "2026_congressional": {
        "scope": "congressional",
        "lines": 2026,
        "plan_id": "SL 2025-95",
        "assignment": ROOT / "data/tmp/block_assign_extract_2026/NC_CD2026.csv",
        "block_col": "GEOID",
        "district_col": "CDFP",
        "live_dir": ROOT / "data/district_contests_2026_lines",
    },
}

NCSBE_FILES = {
    2016: ROOT / "data/2016/20161108__nc__general__precinct.csv",
    2018: ROOT / "data/2018/20181106__nc__general__precinct.csv",
    2020: ROOT / "data/2020/20201103__nc__general__precinct.csv",
    2022: ROOT / "data/2022/20221108__nc__general__precinct.csv",
    2024: ROOT / "data/2024/20241105__nc__general__precinct.csv",
}

MGGG_CONTESTS = {
    "governor_2008": ("EL08G_GV_D", "EL08G_GV_R", ["EL08G_GV_L"]),
    "us_senate_2008": ("EL08G_USS_", "EL08G_US_1", ["EL08G_US_2", "EL08G_US_3"]),
    "us_senate_2010": ("EL10G_USS_", "EL10G_US_1", ["EL10G_US_2", "EL10G_US_3"]),
    "governor_2012": ("EL12G_GV_D", "EL12G_GV_R", ["EL12G_GV_L", "EL12G_GV_W", "EL12G_GV_1"]),
    "president_2012": ("EL12G_PR_D", "EL12G_PR_R", ["EL12G_PR_L", "EL12G_PR_W", "EL12G_PR_1"]),
    "us_senate_2014": ("EL14G_US_1", "EL14G_USS_", ["EL14G_US_2", "EL14G_US_3"]),
}


def load_assignment(spec: dict[str, Any]) -> pd.DataFrame:
    frame = pd.read_csv(spec["assignment"], dtype=str)
    out = frame[[spec["block_col"], spec["district_col"]]].copy()
    out.columns = ["block_geoid20", "district"]
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.strip().str.zfill(15)
    out["district"] = out["district"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    numeric = out["district"].str.match(r"^\d+$", na=False)
    out.loc[numeric, "district"] = out.loc[numeric, "district"].str.lstrip("0")
    out.loc[out["district"] == "", "district"] = "0"
    return out.drop_duplicates("block_geoid20")


def build_weights(block_precinct: pd.DataFrame, plan: pd.DataFrame, vap: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    block_precinct = block_precinct.copy()
    block_precinct["block_geoid20"] = block_precinct["block_geoid20"].astype(str).str.strip().str.zfill(15)
    block_precinct["precinct_id"] = block_precinct["precinct_id"].astype(str).str.strip().str.upper()
    blocks = block_precinct.merge(vap, on="block_geoid20", how="left").merge(plan, on="block_geoid20", how="inner")
    blocks["vap_count"] = pd.to_numeric(blocks["vap_count"], errors="coerce").fillna(0.0)
    grouped = blocks.groupby(["precinct_id", "district"], as_index=False)["vap_count"].sum()
    totals = grouped.groupby("precinct_id")["vap_count"].transform("sum")
    grouped["share"] = (grouped["vap_count"] / totals).where(totals > 0, 0.0)
    grouped = grouped[grouped["share"] > 0][["precinct_id", "district", "share"]]
    grouped["county"] = grouped["precinct_id"].str.split(" - ", n=1).str[0].str.upper()
    county = blocks.copy()
    county["county"] = county["precinct_id"].str.split(" - ", n=1).str[0].str.upper()
    county = county.groupby(["county", "district"], as_index=False)["vap_count"].sum()
    county_total = county.groupby("county")["vap_count"].transform("sum")
    county["share"] = (county["vap_count"] / county_total).where(county_total > 0, 0.0)
    return grouped, county[county["share"] > 0][["county", "district", "share"]]


def integerize(values: pd.Series) -> dict[str, int]:
    positive = values[values > 0].astype(float)
    floors = positive.map(floor).astype(int)
    target = int(round(float(positive.sum())))
    remainder = target - int(floors.sum())
    if remainder > 0:
        fractions = (positive - floors).sort_values(ascending=False, kind="stable")
        for district in fractions.index[:remainder]:
            floors.loc[district] += 1
    return {str(key): int(value) for key, value in floors.items()}


def project_precinct_votes(votes: pd.DataFrame, weights: pd.DataFrame, county_weights: pd.DataFrame) -> tuple[dict[str, dict[str, int]], dict[str, Any]]:
    source = votes.copy()
    source["precinct_id"] = source["precinct_id"].astype(str).str.strip().str.upper()
    matched_keys = set(weights["precinct_id"].astype(str).str.upper())
    source["matched"] = source["precinct_id"].isin(matched_keys)
    matched = source[source["matched"]].merge(weights, on="precinct_id", how="inner")
    unmatched = source[~source["matched"]].copy()
    unmatched["county"] = unmatched["precinct_id"].str.split(" - ", n=1).str[0].str.upper()
    unmatched_alloc = unmatched.merge(county_weights, on="county", how="left")
    output: dict[str, dict[str, int]] = {}
    for party in ("dem_votes", "rep_votes", "other_votes"):
        parts: list[pd.DataFrame] = []
        if not matched.empty:
            frame = matched[["district", party, "share"]].copy()
            frame["allocated"] = pd.to_numeric(frame[party], errors="coerce").fillna(0.0) * frame["share"]
            parts.append(frame[["district", "allocated"]])
        if not unmatched_alloc.empty:
            frame = unmatched_alloc[["district", party, "share"]].dropna(subset=["district", "share"]).copy()
            frame["allocated"] = pd.to_numeric(frame[party], errors="coerce").fillna(0.0) * frame["share"]
            parts.append(frame[["district", "allocated"]])
        grouped = pd.concat(parts, ignore_index=True).groupby("district")["allocated"].sum() if parts else pd.Series(dtype=float)
        output[party] = integerize(grouped)
    total_votes = float(source[["dem_votes", "rep_votes", "other_votes"]].sum().sum())
    unmatched_votes = float(unmatched[["dem_votes", "rep_votes", "other_votes"]].sum().sum())
    source_totals = {
        party: int(round(float(pd.to_numeric(source[party], errors="coerce").fillna(0.0).sum())))
        for party in ("dem_votes", "rep_votes", "other_votes")
    }
    projected_totals = {party: int(sum(output[party].values())) for party in source_totals}
    allocation_delta = {party: projected_totals[party] - source_totals[party] for party in source_totals}
    coverage = {
        "source_precincts": int(len(source)),
        "matched_precincts": int(source["matched"].sum()),
        "unmatched_precincts": int((~source["matched"]).sum()),
        "vote_coverage_pct": round(100.0 * (total_votes - unmatched_votes) / total_votes, 4) if total_votes else 100.0,
        "unmatched_allocated_by": "county_vap_share",
        "source_vote_totals": source_totals,
        "projected_vote_totals": projected_totals,
        "allocation_delta": allocation_delta,
    }
    return output, coverage


def result_rows(projected: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
    districts = sorted(set().union(*(set(values) for values in projected.values())), key=int)
    rows: dict[str, dict[str, Any]] = {}
    for district in districts:
        dem = projected["dem_votes"].get(district, 0)
        rep = projected["rep_votes"].get(district, 0)
        other = projected["other_votes"].get(district, 0)
        total = dem + rep + other
        margin = rep - dem
        rows[district] = {
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": other,
            "total_votes": total,
            "margin": margin,
            "margin_pct": round(100.0 * margin / total, 2) if total else 0.0,
            "winner": "REP" if margin > 0 else ("DEM" if margin < 0 else "TIE"),
        }
    return rows


def prepare_ncsbe(year: int) -> tuple[pd.DataFrame, list[tuple[str, str]], dict[str, str], Path]:
    source_path = NCSBE_FILES[year]
    source = pd.read_csv(source_path, dtype=str, low_memory=False)
    crosswalk_path = district_builder.resolve_vintage_match_crosswalk(year)
    block_precinct = load_crosswalk(crosswalk_path, "precinct_id", "block_geoid20")
    matched_keys = set(block_precinct["precinct_id"].astype(str).str.strip().str.upper())
    source_keys = source["county"].astype(str).str.strip().str.upper() + " - " + source["precinct"].astype(str).str.strip().str.upper()
    automatic = district_builder.build_auto_precinct_overrides(source_keys, matched_keys)
    manual = district_builder.load_precinct_overrides(ROOT / "data/mappings/precinct_key_overrides.csv", year)
    overrides = {
        raw: canonical
        for raw, canonical in {**automatic, **manual}.items()
        if district_builder._norm(raw) not in matched_keys
        and district_builder._norm(canonical) in matched_keys
        and district_builder._norm(raw) != district_builder._norm(canonical)
    }
    judicial = district_builder.load_judicial_office_keys(ROOT / "data/mappings/judicial_seat_crosswalk.csv", year)
    offices: list[tuple[str, str]] = []
    seen: set[str] = set()
    for office in sorted(source["office"].dropna().astype(str).unique()):
        normalized = re.sub(r"\s+", " ", office.strip().upper())
        slug = judicial.get(normalized) or district_builder.infer_office_key(office)
        if slug and slug not in seen:
            offices.append((office.strip(), slug))
            seen.add(slug)
    return source, offices, overrides, crosswalk_path


def build_ncsbe() -> dict[str, Any]:
    vap = pd.read_csv(ROOT / "data/census/block_vap_2020_nc.csv", dtype={"block_geoid20": str})[["block_geoid20", "vap_count"]]
    vap["block_geoid20"] = vap["block_geoid20"].astype(str).str.zfill(15)
    plans = {name: load_assignment(spec) for name, spec in PLAN_SPECS.items()}
    output: dict[str, Any] = {
        name: {
            "spec": {k: source_path_relative(v) if isinstance(v, Path) else v for k, v in spec.items()},
            "contests": {},
        }
        for name, spec in PLAN_SPECS.items()
    }
    for year in sorted(NCSBE_FILES):
        source, offices, overrides, crosswalk_path = prepare_ncsbe(year)
        block_precinct = load_crosswalk(crosswalk_path, "precinct_id", "block_geoid20")
        plan_weights = {name: build_weights(block_precinct, plan, vap) for name, plan in plans.items()}
        for office, slug in offices:
            precinct, dem_candidate, rep_candidate = district_builder.build_precinct_party_votes(
                source, office, precinct_overrides=overrides, election_year=year
            )
            if precinct.empty or precinct["dem_votes"].sum() <= 0 or precinct["rep_votes"].sum() <= 0:
                continue
            for name, (weights, county_weights) in plan_weights.items():
                projected, coverage = project_precinct_votes(precinct, weights, county_weights)
                output[name]["contests"][f"{slug}_{year}"] = {
                    "year": year,
                    "contest_type": slug,
                    "office": office,
                    "dem_candidate": dem_candidate,
                    "rep_candidate": rep_candidate,
                    "source_file": source_path_relative(NCSBE_FILES[year]),
                    "match_crosswalk": source_path_relative(crosswalk_path),
                    "coverage": coverage,
                    "results": result_rows(projected),
                }
    return {
        "schema": "ncsbe_senate_congress_benchmarks.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "North Carolina State Board of Elections precinct general-election files",
        "precinct_geometry_source": "https://dl.ncsbe.gov/?prefix=ShapeFiles/Precinct/",
        "method": "election-vintage precinct to official plan; 2020 VAP split; non-geographic votes allocated by candidate within county",
        "plans": output,
    }


def source_path_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def build_mggg(shapefile_path: Path) -> dict[str, Any]:
    reader = shapefile.Reader(str(shapefile_path))
    fields = [field[0] for field in reader.fields[1:]]
    vtd = pd.DataFrame((dict(zip(fields, record)) for record in reader.records()))
    block_precinct = load_crosswalk(ROOT / "data/crosswalks/block20_to_vtd10.csv", "precinct_id", "block_geoid20")
    block_precinct["precinct_id"] = block_precinct["block_geoid20"].str[:5] + block_precinct["precinct_id"].str.split(" - ", n=1).str[-1].str.strip()
    vap = pd.read_csv(ROOT / "data/census/block_vap_2020_nc.csv", dtype={"block_geoid20": str})[["block_geoid20", "vap_count"]]
    plans: dict[str, Any] = {}
    for name, spec in PLAN_SPECS.items():
        weights, county_weights = build_weights(block_precinct, load_assignment(spec), vap)
        contests: dict[str, Any] = {}
        for key, (dem_col, rep_col, other_cols) in MGGG_CONTESTS.items():
            precinct = pd.DataFrame({
                "precinct_id": vtd["VTD_Key"].astype(str).str.strip(),
                "dem_votes": pd.to_numeric(vtd[dem_col], errors="coerce").fillna(0.0),
                "rep_votes": pd.to_numeric(vtd[rep_col], errors="coerce").fillna(0.0),
                "other_votes": sum(pd.to_numeric(vtd[col], errors="coerce").fillna(0.0) for col in other_cols),
            })
            projected, coverage = project_precinct_votes(precinct, weights, county_weights)
            slug, year_text = key.rsplit("_", 1)
            contests[key] = {
                "year": int(year_text),
                "contest_type": slug,
                "source_file": source_path_relative(shapefile_path),
                "coverage": coverage,
                "results": result_rows(projected),
            }
        plans[name] = {
            "spec": {k: source_path_relative(v) if isinstance(v, Path) else v for k, v in spec.items()},
            "contests": contests,
        }
    return {
        "schema": "mggg_senate_congress_benchmarks.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "https://github.com/mggg-states/NC-shapefiles",
        "method": "MGGG NCGA-derived 2010 VTD election fields to official plan; 2020 VAP split",
        "plans": plans,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("ncsbe", "mggg"), required=True)
    parser.add_argument("--mggg-shapefile", type=Path, default=ROOT / "downloads/mggg/NC_VTD/NC_VTD.shp")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_ncsbe() if args.source == "ncsbe" else build_mggg(args.mggg_shapefile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    summary = {
        name: {
            "contests": len(plan["contests"]),
            "min_vote_coverage_pct": min((item["coverage"]["vote_coverage_pct"] for item in plan["contests"].values()), default=100.0),
        }
        for name, plan in payload["plans"].items()
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
