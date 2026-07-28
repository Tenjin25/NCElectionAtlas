#!/usr/bin/env python3
"""Fetch official pre-/early-shapefile sources for NC precinct reconstruction.

The binary source packages live under downloads/ (gitignored).  A compact,
reproducible inventory is also written to data/reports/urban_sf1_historical so
the official URLs, checksums, sizes, and archive members can be reviewed
without committing the source archives.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


URBAN_COUNTIES = {
    "37021": "Buncombe",
    "37025": "Cabarrus",
    "37051": "Cumberland",
    "37063": "Durham",
    "37067": "Forsyth",
    "37071": "Gaston",
    "37081": "Guilford",
    "37119": "Mecklenburg",
    "37129": "NewHanover",
    "37179": "Union",
    "37183": "Wake",
}

# Official Census county directory indexes, captured 2026-07-28.  Numeric
# sheets are contiguous from 000 through the listed maximum; A01 is the county
# index sheet where present.  Keeping this table avoids relying on fragile
# server-generated HTML while preserving deterministic official PDF URLs.
BLOCK_MAP_SHEETS = {
    "37021": (47, True),
    "37025": (26, False),
    "37051": (45, True),
    "37063": (30, True),
    "37067": (38, True),
    "37071": (33, False),
    "37081": (56, True),
    "37119": (55, True),
    "37129": (23, True),
    "37179": (19, True),
    "37183": (77, True),
}

STATIC_SOURCES = [
    # Census documentation for interpreting the fixed-width TIGER/Line files.
    (
        "census_tiger",
        "tiger_redistricting_readme",
        "https://www2.census.gov/geo/tiger/rd_2ktiger/readme.txt",
        "census/tiger2000/docs/readme.txt",
    ),
    (
        "census_tiger",
        "tiger_redistricting_technical_documentation",
        "https://www2.census.gov/geo/tiger/rd_2ktiger/tgrrd2k.pdf",
        "census/tiger2000/docs/tgrrd2k.pdf",
    ),
    (
        "census_tiger",
        "tiger_2000_technical_documentation",
        "https://www2.census.gov/geo/tiger/tiger2k/tiger2k.pdf",
        "census/tiger2000/docs/tiger2k.pdf",
    ),
    (
        "census_tiger",
        "north_carolina_county_codes",
        "https://www2.census.gov/geo/tiger/rd_2ktiger/NC/counts37.txt",
        "census/tiger2000/docs/counts37.txt",
    ),
    # Original precinct election returns.
    (
        "ncsbe_results",
        "ncsbe_precinct_results_2000_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2000_11_07/results_pct_20001107.zip",
        "ncsbe/results/results_pct_20001107.zip",
    ),
    (
        "ncsbe_results",
        "ncsbe_precinct_results_2002_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2002_11_05/results_pct_20021105.zip",
        "ncsbe/results/results_pct_20021105.zip",
    ),
    (
        "ncsbe_results",
        "ncsbe_precinct_results_2004_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2004_11_02/results_pct_20041102.zip",
        "ncsbe/results/results_pct_20041102.zip",
    ),
    # Historical turnout records provide an independent precinct-name/code list.
    (
        "ncsbe_voter_history",
        "ncsbe_voter_history_stats_2000_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2000_11_07/history_stats_20001107.zip",
        "ncsbe/voter_history/history_stats_20001107.zip",
    ),
    (
        "ncsbe_voter_history",
        "ncsbe_voter_history_stats_2002_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2002_11_05/history_stats_20021105.zip",
        "ncsbe/voter_history/history_stats_20021105.zip",
    ),
    (
        "ncsbe_voter_history",
        "ncsbe_voter_history_stats_2004_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2004_11_02/history_stats_20041102.zip",
        "ncsbe/voter_history/history_stats_20041102.zip",
    ),
    # Election-date registration and absentee files can corroborate precinct
    # lineage and, where voter precinct is present, allocate administrative
    # absentee buckets more defensibly than countywide population.
    (
        "ncsbe_voter_stats",
        "ncsbe_voter_stats_2000_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2000_11_07/voter_stats_20001107.zip",
        "ncsbe/voter_stats/voter_stats_20001107.zip",
    ),
    (
        "ncsbe_voter_stats",
        "ncsbe_voter_stats_2002_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2002_11_05/voter_stats_20021105.zip",
        "ncsbe/voter_stats/voter_stats_20021105.zip",
    ),
    (
        "ncsbe_voter_stats",
        "ncsbe_voter_stats_2004_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2004_11_02/voter_stats_20041102.zip",
        "ncsbe/voter_stats/voter_stats_20041102.zip",
    ),
    (
        "ncsbe_absentee",
        "ncsbe_absentee_2000_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2000_11_07/absentee_20001107.zip",
        "ncsbe/absentee/absentee_20001107.zip",
    ),
    (
        "ncsbe_absentee",
        "ncsbe_absentee_2002_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2002_11_05/absentee_20021105.zip",
        "ncsbe/absentee/absentee_20021105.zip",
    ),
    (
        "ncsbe_absentee",
        "ncsbe_absentee_2004_general",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2004_11_02/absentee_20041102.zip",
        "ncsbe/absentee/absentee_20041102.zip",
    ),
    (
        "ncsbe_precinct_geometry",
        "ncsbe_precincts_2006_general_shapefile",
        "https://s3.amazonaws.com/dl.ncsbe.gov/ShapeFiles/Precinct/Precincts2006Gen.zip",
        "ncsbe/precinct_geometry/Precincts2006Gen.zip",
    ),
]

NCGA_PLANS = [
    # The 1992 plans governed the 2000 election and use 1990 Census blocks.
    ("House_1992", "house_plan_1992_block_assignment"),
    ("Senate_1992", "senate_plan_1992_block_assignment"),
    # Enacted, interim, and court plans help identify district-label lineage.
    ("House_2001", "house_plan_2001_block_assignment"),
    ("Senate_2001", "senate_plan_2001_block_assignment"),
    ("House_2002", "house_plan_2002_block_assignment"),
    ("Senate_2002", "senate_plan_2002_block_assignment"),
    ("House_2002_Court", "house_plan_2002_court_block_assignment"),
    ("Senate_2002_Court", "senate_plan_2002_court_block_assignment"),
    ("House_2003", "house_plan_2003_block_assignment"),
    ("Senate_2003", "senate_plan_2003_block_assignment"),
    # The same congressional plan governed both elections and sharpens
    # House/Senate cell inference where a precinct lies near a plan boundary.
    ("Congress_2001", "congress_plan_2001_block_assignment"),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path, attempts: int = 4) -> dict[str, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size:
        return {"download_status": "existing"}

    partial = target.with_suffix(target.suffix + ".part")
    for attempt in range(1, attempts + 1):
        try:
            headers = {"User-Agent": "NCPrecinctMap historical-source fetcher/1.0"}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as response, partial.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                response_headers = dict(response.headers.items())
            os.replace(partial, target)
            return {
                "download_status": "downloaded",
                "last_modified": response_headers.get("Last-Modified", ""),
                "etag": response_headers.get("ETag", "").strip('"'),
            }
        except Exception:
            if partial.exists():
                partial.unlink()
            if attempt == attempts:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def archive_metadata(path: Path) -> dict[str, object]:
    if path.suffix.lower() != ".zip":
        return {}
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        members = [item.filename for item in archive.infolist() if not item.is_dir()]
    if bad_member:
        raise RuntimeError(f"CRC validation failed for {path}: {bad_member}")
    return {
        "zip_valid": True,
        "archive_member_count": len(members),
        "archive_members": members,
    }


def source_specs(include_maps: bool) -> list[tuple[str, str, str, str]]:
    specs = list(STATIC_SOURCES)

    tiger_root = "https://www2.census.gov/geo/tiger/rd_2ktiger/NC/"
    for fips, county in URBAN_COUNTIES.items():
        specs.append(
            (
                "census_tiger",
                f"tiger2000_{county.lower()}",
                f"{tiger_root}tgr{fips}.zip",
                f"census/tiger2000/counties/tgr{fips}.zip",
            )
        )

    for directory, label in NCGA_PLANS:
        specs.append(
            (
                "ncga_block_assignments",
                label,
                f"https://ncleg.gov/Files/GIS/Plans_Main/{directory}/baf.zip",
                f"ncga/block_assignments/{directory}_baf.zip",
            )
        )

    if include_maps:
        map_root = "https://www2.census.gov/plmap/pl_blk/st37_NorthCarolina/"
        for fips, county in URBAN_COUNTIES.items():
            county_url = f"{map_root}c{fips}_{county}/"
            max_numeric, has_index = BLOCK_MAP_SHEETS[fips]
            filenames = [f"PB{fips}_{sheet:03d}.pdf" for sheet in range(max_numeric + 1)]
            if has_index:
                filenames.append(f"PB{fips}_A01.pdf")
            for filename in filenames:
                link = urllib.parse.urljoin(county_url, filename)
                specs.append(
                    (
                        "census_block_maps",
                        f"census2000_block_map_{county.lower()}_{filename[8:-4].lower()}",
                        link,
                        f"census/block_maps/{fips}_{county}/{filename}",
                    )
                )
    return specs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("downloads/nc_historical_precinct_sources"),
        help="Directory for source packages (default: downloads/nc_historical_precinct_sources)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/urban_sf1_historical/historical_source_manifest.json"),
        help="Compact manifest path",
    )
    parser.add_argument(
        "--skip-maps",
        action="store_true",
        help="Skip the potentially large county block-map PDF collection",
    )
    args = parser.parse_args()

    root = args.output.resolve()
    specs = source_specs(include_maps=not args.skip_maps)
    manifest: dict[str, object] = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Official source inventory for 2000/2002/2004 urban precinct and legislative reconstruction",
        "download_root": str(root),
        "urban_counties": URBAN_COUNTIES,
        "sources": [],
    }

    total = len(specs)
    for index, (category, label, url, relative_path) in enumerate(specs, start=1):
        target = root / relative_path
        print(f"[{index}/{total}] {label}", flush=True)
        status = download(url, target)
        item: dict[str, object] = {
            "category": category,
            "label": label,
            "official_url": url,
            "local_relative_path": relative_path.replace("\\", "/"),
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
            **status,
            **archive_metadata(target),
        }
        manifest["sources"].append(item)  # type: ignore[union-attr]

        # Keep an incremental manifest in the download directory.
        root.mkdir(parents=True, exist_ok=True)
        (root / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    by_category: dict[str, dict[str, int]] = {}
    for item in manifest["sources"]:  # type: ignore[union-attr]
        category = str(item["category"])
        summary = by_category.setdefault(category, {"files": 0, "bytes": 0})
        summary["files"] += 1
        summary["bytes"] += int(item["bytes"])
    manifest["summary_by_category"] = by_category
    manifest["source_count"] = len(manifest["sources"])  # type: ignore[arg-type]
    manifest["total_bytes"] = sum(
        int(item["bytes"]) for item in manifest["sources"]  # type: ignore[union-attr]
    )

    serialized = json.dumps(manifest, indent=2) + "\n"
    (root / "manifest.json").write_text(serialized, encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(serialized, encoding="utf-8")
    print(f"Wrote {args.report} ({manifest['source_count']} sources)", flush=True)


if __name__ == "__main__":
    main()
