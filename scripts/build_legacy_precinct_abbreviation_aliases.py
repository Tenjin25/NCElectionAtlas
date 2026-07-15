"""Build audited legacy precinct abbreviation aliases against SBE2006 attributes.

The source TSVs expose a county-local `precinct_abbrv`/code field.  For early
results whose precinct rows carry only that code, this artifact records cases
where the abbreviation exactly matches the SBE2006 `SEIMS_Code` for the county.
Name-only sources, such as 2008, are included as validation rows without adding
new abbreviation aliases.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import geopandas as gpd

try:
    from build_district_results_2024_lines import NC_COUNTY_FIPS
except ModuleNotFoundError:  # pragma: no cover - supports package-style imports in ad hoc audits
    from scripts.build_district_results_2024_lines import NC_COUNTY_FIPS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SBE2006_SHP = ROOT / "data" / "Precincts2006Gen" / "Precincts2006Gen.shp"
DEFAULT_VTD00_GEOJSON = ROOT / "data" / "census" / "tl_2008_37_vtd00_merged.geojson"
DEFAULT_OUTPUT = ROOT / "data" / "mappings" / "legacy_precinct_abbreviation_to_sbe2006.csv"

SOURCE_FILES = {
    2000: Path("C:/Users/Shama/Downloads/results_pct_20001107/results_pct_20001107.txt"),
    2002: Path("C:/Users/Shama/Downloads/results_pct_20021105/results_pct_20021105.txt"),
    2004: Path("C:/Users/Shama/Downloads/results_pct_20041102/results_pct_20041102.txt"),
    2008: Path("C:/Users/Shama/Downloads/results_pct_20081104/results_pct_20081104.txt"),
}

URBAN_COUNTIES = {
    "BUNCOMBE",
    "CABARRUS",
    "CUMBERLAND",
    "DURHAM",
    "FORSYTH",
    "GASTON",
    "GUILFORD",
    "MECKLENBURG",
    "NEW HANOVER",
    "UNION",
    "WAKE",
}


def norm_token(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def compact_name(value: object) -> str:
    text = norm_token(value)
    text = text.replace("&", " AND ")
    text = re.sub(r"\bMTN\b", "MOUNTAIN", text)
    text = re.sub(r"\bMT\b", "MOUNT", text)
    text = text.replace("#", " ")
    return re.sub(r"[^A-Z0-9]+", "", text)


def source_name_keys(value: object) -> set[str]:
    key = compact_name(value)
    keys = {key} if key else set()
    if key == "FLINTGROVES":
        keys.add("FLINTGROVE")
    group_stripped = re.sub(r"G\d+[A-Z]?$", "", key)
    if group_stripped and group_stripped != key:
        keys.add(group_stripped)
    return keys


def read_source_pairs(year: int, path: Path, counties: set[str]) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    if not path.exists():
        return out

    if year == 2004:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                county = norm_token(row.get("county"))
                abbr = norm_token(row.get("precinct_abbrv"))
                name = norm_token(row.get("precinct"))
                if county in counties and abbr:
                    out.setdefault((county, abbr), set()).add(name)
        return out

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for row in reader:
            if len(row) < 4:
                continue
            county = norm_token(row[0])
            abbr = norm_token(row[2])
            name = norm_token(row[3])
            if county in counties and abbr:
                out.setdefault((county, abbr), set()).add(name)
    return out


def read_source_names(year: int, path: Path, counties: set[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if year != 2008 or not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            county = norm_token(row.get("county"))
            name = norm_token(row.get("precinct"))
            if county in counties and name:
                out.setdefault(county, set()).add(name)
    return out


def read_vtd00_pairs(path: Path, counties: set[str]) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    if not path.exists():
        return out
    gdf = gpd.read_file(path)
    needed = {"COUNTYFP00", "VTDST00", "NAME00"}
    missing = needed - set(gdf.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    for _, row in gdf.iterrows():
        county = NC_COUNTY_FIPS.get(str(row.get("COUNTYFP00") or "").strip().zfill(3), "")
        code = norm_token(row.get("VTDST00"))
        name = norm_token(row.get("NAME00"))
        if county in counties and code:
            out.setdefault((county, code), set()).add(name)
    return out


def read_vtd00_names(path: Path, counties: set[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if not path.exists():
        return out
    gdf = gpd.read_file(path)
    needed = {"COUNTYFP00", "NAME00"}
    missing = needed - set(gdf.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    for _, row in gdf.iterrows():
        county = NC_COUNTY_FIPS.get(str(row.get("COUNTYFP00") or "").strip().zfill(3), "")
        name = norm_token(row.get("NAME00"))
        if county in counties and name:
            out.setdefault(county, set()).add(name)
    return out


def load_sbe2006(path: Path, counties: set[str]) -> dict[tuple[str, str], dict[str, str]]:
    gdf = gpd.read_file(path)
    out: dict[tuple[str, str], dict[str, str]] = {}
    for _, row in gdf.iterrows():
        county = norm_token(row.get("County"))
        code = norm_token(row.get("SEIMS_Code"))
        precinct = norm_token(row.get("Precinct"))
        desc = norm_token(row.get("SEIMS_Desc"))
        if county not in counties or not code or not precinct:
            continue
        out[(county, code)] = {
            "county": county,
            "sbe2006_seims_code": code,
            "sbe2006_precinct": precinct,
            "sbe2006_key": f"{county} - {precinct}",
            "sbe2006_desc": desc,
        }
    return out


def code_aliases(code: str) -> set[str]:
    code = norm_token(code)
    aliases = {code}
    if re.fullmatch(r"0+\d+", code):
        aliases.add(str(int(code)))
    return {alias for alias in aliases if alias}


def confidence_for(abbr: str, names: set[str], sbe: dict[str, str]) -> tuple[str, str]:
    sbe_keys = source_name_keys(sbe["sbe2006_precinct"]) | source_name_keys(sbe.get("sbe2006_desc"))
    source_keys = set().union(*(source_name_keys(name) for name in names if name))
    if source_keys & sbe_keys:
        return "high", "exact abbreviation and compatible source/SBE2006 name"
    if source_keys and source_keys <= {compact_name(abbr), "ABSENTEEPROVISIONAL"}:
        return "high", "exact abbreviation; source name is code-only/non-geographic label"
    return "medium", "exact abbreviation; source/SBE2006 names differ"


def append_name_validation_rows(
    rows: list[dict[str, str]],
    *,
    source_names: dict[str, set[str]],
    sbe: dict[tuple[str, str], dict[str, str]],
    year: str,
    source_file: Path,
    notes: str,
) -> None:
    sbe_by_name: dict[tuple[str, str], list[dict[str, str]]] = {}
    for sbe_row in sbe.values():
        for key in source_name_keys(sbe_row["sbe2006_precinct"]) | source_name_keys(sbe_row.get("sbe2006_desc")):
            sbe_by_name.setdefault((sbe_row["county"], key), []).append(sbe_row)
    for county, names in sorted(source_names.items()):
        for source_name in sorted(names):
            matches: dict[str, dict[str, str]] = {}
            for key in source_name_keys(source_name):
                for sbe_row in sbe_by_name.get((county, key), []):
                    matches[sbe_row["sbe2006_key"]] = sbe_row
            if len(matches) != 1:
                continue
            sbe_row = next(iter(matches.values()))
            rows.append(
                {
                    "county": county,
                    "year": year,
                    "precinct_abbrv": "",
                    "source_precinct": source_name,
                    "sbe2006_seims_code": sbe_row["sbe2006_seims_code"],
                    "sbe2006_precinct": sbe_row["sbe2006_precinct"],
                    "sbe2006_key": sbe_row["sbe2006_key"],
                    "alias_values": "",
                    "confidence": "verified",
                    "source_file": str(source_file).replace("\\", "/"),
                    "notes": notes,
                }
            )


def build_rows(
    source_files: dict[int, Path],
    sbe2006_shp: Path,
    counties: set[str],
    *,
    vtd00_geojson: Path = DEFAULT_VTD00_GEOJSON,
) -> list[dict[str, str]]:
    sbe = load_sbe2006(sbe2006_shp, counties)
    rows: list[dict[str, str]] = []
    for year, path in sorted(source_files.items()):
        pairs = read_source_pairs(year, path, counties)
        for (county, abbr), names in sorted(pairs.items()):
            sbe_row = sbe.get((county, abbr))
            if not sbe_row:
                continue
            confidence, notes = confidence_for(abbr, names, sbe_row)
            if confidence != "high":
                continue
            source_name = " | ".join(sorted(name for name in names if name))
            rows.append(
                {
                    "county": county,
                    "year": str(year),
                    "precinct_abbrv": abbr,
                    "source_precinct": source_name,
                    "sbe2006_seims_code": sbe_row["sbe2006_seims_code"],
                    "sbe2006_precinct": sbe_row["sbe2006_precinct"],
                    "sbe2006_key": sbe_row["sbe2006_key"],
                    "alias_values": ";".join(sorted(code_aliases(abbr))),
                    "confidence": confidence,
                    "source_file": str(path).replace("\\", "/"),
                    "notes": notes,
                }
            )
        source_names = read_source_names(year, path, counties)
        append_name_validation_rows(
            rows,
            source_names=source_names,
            sbe=sbe,
            year=str(year),
            source_file=path,
            notes="name-only source row validates SBE2006 precinct label; no abbreviation alias emitted",
        )

    vtd_pairs = read_vtd00_pairs(vtd00_geojson, counties)
    for (county, code), names in sorted(vtd_pairs.items()):
        sbe_row = sbe.get((county, code))
        if not sbe_row:
            continue
        confidence, notes = confidence_for(code, names, sbe_row)
        if confidence != "high":
            continue
        rows.append(
            {
                "county": county,
                "year": "2000",
                "precinct_abbrv": code,
                "source_precinct": " | ".join(sorted(name for name in names if name)),
                "sbe2006_seims_code": sbe_row["sbe2006_seims_code"],
                "sbe2006_precinct": sbe_row["sbe2006_precinct"],
                "sbe2006_key": sbe_row["sbe2006_key"],
                "alias_values": ";".join(sorted(code_aliases(code))),
                "confidence": confidence,
                "source_file": str(vtd00_geojson).replace("\\", "/"),
                "notes": f"{notes}; VTD00 code/name matched SBE2006",
            }
        )
    append_name_validation_rows(
        rows,
        source_names=read_vtd00_names(vtd00_geojson, counties),
        sbe=sbe,
        year="2000",
        source_file=vtd00_geojson,
        notes="VTD00 NAME00 validates SBE2006 precinct label; no abbreviation alias emitted",
    )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbe2006-shp", type=Path, default=DEFAULT_SBE2006_SHP)
    parser.add_argument("--vtd00-geojson", type=Path, default=DEFAULT_VTD00_GEOJSON)
    parser.add_argument("--out-csv", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--county", action="append", default=[])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counties = {norm_token(c) for c in args.county if norm_token(c)} or URBAN_COUNTIES
    rows = build_rows(SOURCE_FILES, args.sbe2006_shp, counties, vtd00_geojson=args.vtd00_geojson)
    out = args.out_csv if args.out_csv.is_absolute() else ROOT / args.out_csv
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "county",
        "year",
        "precinct_abbrv",
        "source_precinct",
        "sbe2006_seims_code",
        "sbe2006_precinct",
        "sbe2006_key",
        "alias_values",
        "confidence",
        "source_file",
        "notes",
    ]
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    by_county: dict[str, int] = {}
    for row in rows:
        by_county[row["county"]] = by_county.get(row["county"], 0) + 1
    print(f"Wrote {out.relative_to(ROOT)} ({len(rows):,} rows)")
    print(", ".join(f"{county}={count}" for county, count in sorted(by_county.items())))


if __name__ == "__main__":
    main()
