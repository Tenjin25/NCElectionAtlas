#!/usr/bin/env python3
"""Aggregate historical absentee records into privacy-safe plan-cell evidence."""

from __future__ import annotations

import csv
import re
import zipfile
from collections import Counter, defaultdict
from io import TextIOWrapper
from pathlib import Path

import shapefile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "downloads/nc_historical_precinct_sources/ncsbe/absentee"
REJECTED = ROOT / "data/reports/urban_sf1_historical/rejected_direct_vtd.csv"
OUT_PRECINCT = (
    ROOT / "data/reports/urban_sf1_historical/absentee_precinct_plan_cell_evidence.csv"
)
OUT_COUNTY = (
    ROOT / "data/reports/urban_sf1_historical/absentee_county_plan_cell_distribution.csv"
)
ARCHIVES = {
    2002: SOURCE_ROOT / "absentee_20021105.zip",
    2004: SOURCE_ROOT / "absentee_20041102.zip",
}
SBE2006 = ROOT / "data/Precincts2006Gen/Precincts2006Gen.shp"


def norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def precinct_norm(value: object) -> str:
    text = re.sub(r"^\s*PRECINCT\s+", "", str(value or ""), flags=re.I)
    return norm(text)


def district(value: object) -> str:
    match = re.search(r"(\d+)", str(value or ""))
    return str(int(match.group(1))) if match else ""


def candidates(raw_precinct: str) -> set[str]:
    raw = str(raw_precinct or "").strip()
    prefix, _, tail = raw.partition(" ")
    values = {norm(raw), norm(prefix), norm(tail)}
    return {value for value in values if value}


def load_sbe2006_index() -> dict[tuple[str, str], set[tuple[str, str, str]]]:
    reader = shapefile.Reader(str(SBE2006))
    fields = [field[0] for field in reader.fields[1:]]
    output: dict[tuple[str, str], set[tuple[str, str, str]]] = defaultdict(set)
    for record in reader.iterRecords():
        row = dict(zip(fields, record))
        county = str(row.get("County") or "").strip().upper()
        values = (
            str(row.get("SEIMS_Code") or "").strip(),
            str(row.get("SEIMS_Desc") or "").strip(),
            str(row.get("Precinct") or "").strip(),
        )
        for value in values:
            if county and norm(value):
                output[(county, norm(value))].add(values)
    return output


def read_returned_cells(
    year: int, path: Path
) -> tuple[
    dict[tuple[str, str], Counter[tuple[str, str, str]]],
    dict[str, Counter[tuple[str, str, str]]],
]:
    by_precinct: dict[tuple[str, str], Counter[tuple[str, str, str]]] = defaultdict(
        Counter
    )
    by_county: dict[str, Counter[tuple[str, str, str]]] = defaultdict(Counter)
    with zipfile.ZipFile(path) as archive:
        member = next(
            item
            for item in archive.infolist()
            if item.filename.lower().endswith(".txt")
        )
        with archive.open(member) as raw, TextIOWrapper(
            raw, encoding="utf-8-sig", errors="replace", newline=""
        ) as text:
            for row in csv.DictReader(text, delimiter="\t"):
                lowered = {str(key or "").lower(): value for key, value in row.items()}
                if not str(lowered.get("ballot_rtn_dt") or "").strip():
                    continue
                county = str(lowered.get("county_desc") or "").strip().upper()
                precinct = str(lowered.get("precinct_desc") or "").strip()
                if not county or not precinct:
                    continue
                cell = (
                    district(lowered.get("nc_house_desc")),
                    district(lowered.get("nc_senate_desc")),
                    district(lowered.get("cong_dist_desc")),
                )
                by_precinct[(county, precinct_norm(precinct))][cell] += 1
                by_county[county][cell] += 1
    return by_precinct, by_county


def main() -> None:
    with REJECTED.open(newline="", encoding="utf-8-sig") as source:
        rejected = list(csv.DictReader(source))
    sbe2006 = load_sbe2006_index()

    precinct_rows: list[dict[str, object]] = []
    county_rows: list[dict[str, object]] = []
    for year, archive in ARCHIVES.items():
        by_precinct, by_county = read_returned_cells(year, archive)
        for row in rejected:
            if int(row["year"]) != year:
                continue
            county = row["county"].strip().upper()
            matched = [
                (key, counts)
                for (found_county, key), counts in by_precinct.items()
                if found_county == county and key in candidates(row["raw_precinct"])
            ]
            combined: Counter[tuple[str, str, str]] = Counter()
            matched_keys: list[str] = []
            for key, counts in matched:
                matched_keys.append(key)
                combined.update(counts)
            shape_matches: set[tuple[str, str, str]] = set()
            for key in candidates(row["raw_precinct"]):
                shape_matches.update(sbe2006.get((county, key), set()))
            total = sum(combined.values())
            top_cell, top_votes = combined.most_common(1)[0] if combined else (("", "", ""), 0)
            precinct_rows.append(
                {
                    "year": year,
                    "county": county,
                    "raw_precinct": row["raw_precinct"],
                    "matched_precinct_keys": ";".join(sorted(set(matched_keys))),
                    "returned_absentee_voters": total,
                    "plan_cell_count": len(combined),
                    "top_house": top_cell[0],
                    "top_senate": top_cell[1],
                    "top_congressional": top_cell[2],
                    "top_cell_voters": top_votes,
                    "top_cell_share": round(top_votes / total, 6) if total else 0,
                    "house_districts": ";".join(
                        sorted({cell[0] for cell in combined if cell[0]}, key=int)
                    ),
                    "senate_districts": ";".join(
                        sorted({cell[1] for cell in combined if cell[1]}, key=int)
                    ),
                    "congressional_districts": ";".join(
                        sorted({cell[2] for cell in combined if cell[2]}, key=int)
                    ),
                    "sbe2006_match_count": len(shape_matches),
                    "sbe2006_matches": ";".join(
                        f"{code}|{desc}|{name}"
                        for code, desc, name in sorted(shape_matches)
                    ),
                }
            )

        for county, counts in sorted(by_county.items()):
            total = sum(counts.values())
            for (house, senate, congressional), voters in counts.most_common():
                county_rows.append(
                    {
                        "year": year,
                        "county": county,
                        "house": house,
                        "senate": senate,
                        "congressional": congressional,
                        "returned_absentee_voters": voters,
                        "county_share": round(voters / total, 8) if total else 0,
                    }
                )

    OUT_PRECINCT.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PRECINCT.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(precinct_rows[0]))
        writer.writeheader()
        writer.writerows(precinct_rows)
    with OUT_COUNTY.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(county_rows[0]))
        writer.writeheader()
        writer.writerows(county_rows)
    absentee_matched = sum(
        int(row["returned_absentee_voters"]) > 0 for row in precinct_rows
    )
    shape_matched = sum(int(row["sbe2006_match_count"]) > 0 for row in precinct_rows)
    print(
        f"Wrote {OUT_PRECINCT} "
        f"({absentee_matched}/{len(precinct_rows)} absentee matches; "
        f"{shape_matched}/{len(precinct_rows)} SBE2006 matches)"
    )
    print(f"Wrote {OUT_COUNTY} ({len(county_rows)} county plan cells)")


if __name__ == "__main__":
    main()
