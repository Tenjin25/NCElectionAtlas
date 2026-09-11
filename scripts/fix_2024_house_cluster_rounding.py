#!/usr/bin/env python3
"""Lock small House-cluster rounding drift on 2024 lines without changing totals."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "district_contests"
DEST_DIR = ROOT / "data" / "district_contests_2024_lines"

# Districts composed of exactly the same complete counties in both plans.
# Districts containing any county split (notably HD-24/25 in Nash) are excluded.
WHOLE_COUNTY_CLUSTERS = {
    5: ("CAMDEN", "GATES", "HERTFORD", "PASQUOTANK"),
    12: ("GREENE", "JONES", "LENOIR"),
    22: ("BLADEN", "SAMPSON"),
    23: ("BERTIE", "EDGECOMBE", "MARTIN"),
    27: ("HALIFAX", "NORTHAMPTON", "WARREN"),
    48: ("HOKE", "SCOTLAND"),
    65: ("ROCKINGHAM",),
    67: ("MONTGOMERY", "STANLY"),
    86: ("BURKE",),
    97: ("LINCOLN",),
    118: ("HAYWOOD", "MADISON"),
    119: ("JACKSON", "SWAIN", "TRANSYLVANIA"),
    120: ("CHEROKEE", "CLAY", "GRAHAM", "MACON"),
}
VOTE_FIELDS = ("dem_votes", "rep_votes", "other_votes")
NEVER_TOUCH = {24, 25}


def competitiveness_color(margin_pct: float) -> str:
    absolute = abs(margin_pct)
    republican = margin_pct > 0
    if absolute < 0.5:
        return "#f7f7f7"
    if absolute >= 40:
        return "#67000d" if republican else "#08306b"
    if absolute >= 30:
        return "#a50f15" if republican else "#08519c"
    if absolute >= 20:
        return "#cb181d" if republican else "#3182bd"
    if absolute >= 10:
        return "#ef3b2c" if republican else "#6baed6"
    if absolute >= 5.5:
        return "#fb6a4a" if republican else "#9ecae1"
    if absolute >= 1:
        return "#fcae91" if republican else "#c6dbef"
    return "#fee8c8" if republican else "#e1f5fe"


def finalize(row: dict) -> None:
    total = sum(int(row[field]) for field in VOTE_FIELDS)
    margin = int(row["rep_votes"]) - int(row["dem_votes"])
    row["total_votes"] = total
    row["margin"] = margin
    row["margin_pct"] = round(100 * margin / total, 2) if total else 0
    row["winner"] = "REP" if margin > 0 else "DEM" if margin < 0 else "TIE"
    row["competitiveness"] = {"color": competitiveness_color(row["margin_pct"])}


def totals(rows: dict[str, dict]) -> dict[str, int]:
    return {
        field: sum(int(row.get(field, 0) or 0) for row in rows.values())
        for field in VOTE_FIELDS
    }


def artifact_recipients() -> tuple[int, ...]:
    """Rank districts receiving microscopic overlaps from cluster counties."""
    intended = {
        county: district
        for district, counties in WHOLE_COUNTY_CLUSTERS.items()
        for county in counties
    }
    leaked_area: dict[int, float] = defaultdict(float)
    path = ROOT / "data" / "crosswalks" / "precinct_to_2024_state_house.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            precinct_key = str(row.get("precinct_key", "")).upper()
            county = precinct_key.split(" - ", 1)[0]
            if county not in intended:
                continue
            district = int(row["district"])
            if district != intended[county]:
                leaked_area[district] += float(row.get("intersect_area_m2", 0) or 0)
    return tuple(
        district
        for district, _ in sorted(leaked_area.items(), key=lambda item: item[1], reverse=True)
        if district not in WHOLE_COUNTY_CLUSTERS and district not in NEVER_TOUCH
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    recipients = artifact_recipients()
    if not recipients:
        raise RuntimeError("No topology-artifact recipient districts found")

    report = []
    for source_path in sorted(SOURCE_DIR.glob("state_house_*.json")):
        if source_path.name.startswith("state_house_state_house_"):
            continue
        dest_path = DEST_DIR / source_path.name
        if not dest_path.exists():
            continue

        source = json.loads(source_path.read_text(encoding="utf-8"))
        destination = json.loads(dest_path.read_text(encoding="utf-8"))
        source_rows = source["general"]["results"]
        dest_rows = destination["general"]["results"]
        if len(dest_rows) != 120:
            continue

        original_totals = totals(dest_rows)
        changed = []
        skipped = []
        for district in WHOLE_COUNTY_CLUSTERS:
            key = str(district)
            if key not in source_rows or key not in dest_rows:
                continue
            canonical = source_rows[key]
            current = dest_rows[key]
            candidates_match = all(
                str(canonical.get(field, "")) == str(current.get(field, ""))
                for field in ("dem_candidate", "rep_candidate")
            )
            vote_gap = sum(
                abs(int(canonical.get(field, 0) or 0) - int(current.get(field, 0) or 0))
                for field in VOTE_FIELDS
            )
            # This pass is specifically for tiny geometry/rounding residue. Large
            # differences generally indicate distinct historical calibration or
            # nonpartisan candidate bucketing and must not be papered over here.
            if not candidates_match or vote_gap > 100:
                skipped.append(
                    {
                        "district": district,
                        "reason": "candidate buckets differ" if not candidates_match else "not rounding-scale",
                        "vote_gap": vote_gap,
                    }
                )
                continue
            if dest_rows[key] != canonical:
                dest_rows[key] = dict(canonical)
                changed.append(district)

        locked_totals = totals(dest_rows)
        adjustments = {
            field: original_totals[field] - locked_totals[field]
            for field in VOTE_FIELDS
        }
        balanced = []
        for field, amount in adjustments.items():
            if not amount:
                continue
            step = 1 if amount > 0 else -1
            for offset in range(abs(amount)):
                district = str(recipients[offset % len(recipients)])
                if int(dest_rows[district][field]) + step < 0:
                    raise ValueError(f"Negative {field} in HD-{district}")
                dest_rows[district][field] = int(dest_rows[district][field]) + step
                balanced.append((int(district), field, step))

        for district in {str(item[0]) for item in balanced}:
            finalize(dest_rows[district])

        final_totals = totals(dest_rows)
        if final_totals != original_totals:
            raise AssertionError(
                f"Statewide totals changed in {dest_path.name}: "
                f"{original_totals} -> {final_totals}"
            )

        report.append(
            {
                "file": dest_path.name,
                "locked": changed,
                "statewide_adjustments": adjustments,
                "artifact_balancing": balanced,
                "skipped": skipped,
            }
        )
        if args.write and (changed or balanced):
            destination["general"]["results"] = dest_rows
            dest_path.write_text(
                json.dumps(destination, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    print(json.dumps({"mode": "write" if args.write else "audit", "files": report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
