#!/usr/bin/env python3
"""Extract county-level Census 2000 block VAP and geography from SF1 archives.

SF1 file 01 contains tables P001-P005. P005001 is the total population
18 years and over. The fixed-width geographic header supplies LOGRECNO,
block GEOID components, 2000 place/VTD codes, and contemporaneous legislative
and congressional district codes. These fields let downstream work use the
actual Census 2000 voting-district assignment instead of a later TIGER proxy.
"""
from __future__ import annotations

import argparse
import csv
import io
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data/reports/mecklenburg_block_vap_2000_sf1.csv"

# Zero-based CSV position in SF1 file 01:
# five linkage columns + P001 (1) + P002 (6) + P003 (71) + P004 (73).
P005001_COLUMN = 5 + 1 + 6 + 71 + 73


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geo-zip", type=Path, required=True, help="State ncgeo_uf1.zip archive.")
    parser.add_argument(
        "--segment1-zip",
        type=Path,
        required=True,
        help="State nc00001_uf1.zip archive containing tables P001-P005.",
    )
    parser.add_argument("--state-fips", default="37")
    parser.add_argument(
        "--county-fips",
        default="119",
        help="Three-digit county FIPS, or ALL for every county in the state archive.",
    )
    parser.add_argument("--out-csv", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def only_member(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.lower().endswith(suffix.lower())]
    if len(matches) != 1:
        raise ValueError(f"Expected one {suffix} member in {archive.filename}; found {matches}")
    return matches[0]


def load_block_geography(
    geo_zip: Path, state_fips: str, county_fips: str | None
) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with zipfile.ZipFile(geo_zip) as archive:
        member = only_member(archive, "geo.uf1")
        with archive.open(member) as raw:
            for line_bytes in raw:
                line = line_bytes.decode("latin1")
                # Census 2000 SF1 geographic-header positions are zero-based here.
                if line[8:11] != "101":  # Census block summary level
                    continue
                record_county = line[31:34]
                if line[29:31] != state_fips:
                    continue
                if county_fips is not None and record_county != county_fips:
                    continue
                logrecno = line[18:25]
                tract = line[55:61]
                block = line[62:66]
                out[logrecno] = {
                    "block_geoid00": f"{state_fips}{record_county}{tract}{block}",
                    "county_fips_2000": record_county,
                    # SF1 technical documentation positions are one-based:
                    # PLACE 46/5, CD106 137/2, SLDU 145/3, SLDL 148/3, VTD 151/6.
                    "place_fips_2000": line[45:50].strip(),
                    "cd106_2000": line[136:138].strip(),
                    "sldu_2000": line[144:147].strip(),
                    "sldl_2000": line[147:150].strip(),
                    "vtd_code_2000": line[150:156].strip(),
                }
    return out


def extract_vap(
    segment1_zip: Path, geography: dict[str, dict[str, str]]
) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    with zipfile.ZipFile(segment1_zip) as archive:
        member = only_member(archive, "00001.uf1")
        with archive.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="latin1", newline="")
            for row in csv.reader(text):
                if len(row) <= P005001_COLUMN:
                    continue
                geo = geography.get(row[4])
                if not geo:
                    continue
                vap = int(row[P005001_COLUMN] or 0)
                rows.append({**geo, "vap_count_2000": vap})
    return sorted(rows, key=lambda row: str(row["block_geoid00"]))


def main() -> None:
    args = parse_args()
    state_fips = str(args.state_fips).zfill(2)
    county_arg = str(args.county_fips).strip()
    county_fips = None if county_arg.upper() in {"ALL", "*"} else county_arg.zfill(3)
    geography = load_block_geography(args.geo_zip, state_fips, county_fips)
    if not geography:
        raise ValueError(
            f"No block records found for state={state_fips}, "
            f"county={county_fips or 'ALL'}"
        )
    rows = extract_vap(args.segment1_zip, geography)
    if len(rows) != len(geography):
        raise ValueError(f"SF1 join incomplete: geography={len(geography):,}, data={len(rows):,}")
    if len({str(row["block_geoid00"]) for row in rows}) != len(rows):
        raise ValueError("Duplicate block GEOIDs after SF1 extraction.")

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"Wrote {len(rows):,} blocks -> {args.out_csv}; "
        f"VAP={sum(int(row['vap_count_2000']) for row in rows):,}; "
        f"nonzero={sum(int(row['vap_count_2000']) > 0 for row in rows):,}; "
        f"VTDs={len({str(row['vtd_code_2000']) for row in rows}):,}"
    )


if __name__ == "__main__":
    main()
