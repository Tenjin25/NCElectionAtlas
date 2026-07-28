#!/usr/bin/env python3
"""Compare Mecklenburg 2004 precinct labels with SF1 VTD/NCGA plan cells."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

import build_urban_sf1_historical_legislative_weights as weights


ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data/2004/20041102__nc__general__precinct.csv"
SF1 = ROOT / "data/reports/nc_block_vap_geography_2000_sf1.csv"
SOURCE_ROOT = ROOT / "downloads/nc_historical_precinct_sources"
REPORT_DIR = ROOT / "data/reports/urban_sf1_historical"


def main() -> None:
    vap = pd.read_csv(SF1, dtype=str).fillna("")
    vap = vap[vap["county_fips_2000"] == "119"].copy()
    vap["blk2000ge"] = weights.clean_geoid(vap["block_geoid00"])
    plan = weights.load_plan_blocks(SOURCE_ROOT, 2004, vap)
    plan = plan.merge(
        vap[["blk2000ge", "vtd_code_2000"]], on="blk2000ge", how="left"
    )
    plan["vtd"] = plan["vtd_code_2000"].map(weights.code_norm)

    vtd_cells: dict[str, dict[str, set[str]]] = {}
    for vtd, rows in plan.groupby("vtd"):
        vtd_cells[vtd] = {
            chamber: {
                weights.clean_district(value)
                for value in rows[f"plan_{chamber}"]
                if weights.clean_district(value)
            }
            for chamber in ("house", "senate", "congressional")
        }

    raw_totals: dict[tuple[str, str], dict[str, dict[str, int]]] = defaultdict(
        lambda: {
            "house": defaultdict(int),
            "senate": defaultdict(int),
            "congressional": defaultdict(int),
        }
    )
    with RESULTS.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if weights.norm(row.get("county")) != "MECKLENBURG":
                continue
            parsed = weights.district_from_office(row)
            if not parsed:
                continue
            chamber, district = parsed
            raw = str(row.get("precinct") or "").strip()
            raw_totals[("MECKLENBURG", raw)][chamber][district] += int(
                float(row.get("votes") or 0)
            )

    details = []
    for (_, raw), chambers in sorted(raw_totals.items()):
        token = weights.code_norm(weights.prefix_token(raw))
        cells = vtd_cells.get(token)
        if not cells:
            continue
        row = {"raw_precinct": raw, "vtd_code": token}
        all_equal = True
        any_overlap = False
        for chamber in ("house", "senate", "congressional"):
            raw_set = {
                district
                for district, votes in chambers[chamber].items()
                if district and votes > 0
            }
            plan_set = cells[chamber]
            equal = raw_set == plan_set if raw_set else None
            overlap = bool(raw_set & plan_set)
            if raw_set:
                all_equal &= bool(equal)
                any_overlap |= overlap
            row[f"raw_{chamber}"] = ";".join(sorted(raw_set))
            row[f"vtd_plan_{chamber}"] = ";".join(sorted(plan_set))
            row[f"{chamber}_equal"] = equal
            row[f"{chamber}_overlap"] = overlap
        row["all_observed_chambers_equal"] = all_equal
        row["any_observed_chamber_overlap"] = any_overlap
        details.append(row)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    detail_path = REPORT_DIR / "mecklenburg_2004_vtd_plan_cell_audit.csv"
    pd.DataFrame(details).to_csv(detail_path, index=False)
    summary = {
        "schema": "mecklenburg_2004_vtd_plan_cell_audit.v1",
        "matched_vtd_codes": len(details),
        "all_observed_chambers_equal": sum(
            bool(row["all_observed_chambers_equal"]) for row in details
        ),
        "has_observed_plan_overlap": sum(
            bool(row["any_observed_chamber_overlap"]) for row in details
        ),
        "no_observed_plan_overlap": sum(
            not bool(row["any_observed_chamber_overlap"]) for row in details
        ),
        "detail_csv": detail_path.relative_to(ROOT).as_posix(),
    }
    summary_path = REPORT_DIR / "mecklenburg_2004_vtd_plan_cell_audit.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
