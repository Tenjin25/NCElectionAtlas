#!/usr/bin/env python3
"""Reaggregate pre-2018 judicial contests into data/contests (county + precinct layers).

Uses OpenElections precinct CSVs + judicial_candidate_party_overrides.csv via the
existing build_district_contests_from_batch_shatter helpers. Writes the same
contest-slice JSON layout already used by the Counties / Precincts views.

Skips seats that are not major-party contested after overrides (unopposed,
same-party-only generals, blank DEM or REP totals).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_district_contests_from_batch_shatter import (  # noqa: E402
    build_auto_precinct_overrides,
    build_contests_manifest_entry,
    build_precinct_contest_payload,
    build_precinct_party_votes,
    clean_precinct_name,
    infer_office_key,
    load_judicial_candidate_party_overrides,
    load_precinct_overrides,
    load_sbe_precinct_code_map,
    resolve_vintage_match_crosswalk,
    update_contests_manifest,
)
import build_district_contests_from_batch_shatter as builder  # noqa: E402

JUDICIAL_KEY_RE = re.compile(r"^(nc_supreme_court_|nc_court_of_appeals_)")
DEFAULT_YEARS = (2008, 2010, 2012, 2014, 2016)


def find_general_precinct_csv(year: int) -> Path:
    year_dir = ROOT / "data" / str(year)
    if not year_dir.is_dir():
        raise FileNotFoundError(f"Missing year dir: {year_dir}")
    matches = sorted(
        year_dir.glob("*__nc__general__precinct.csv"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(f"No general precinct CSV under {year_dir}")
    return matches[0]


def sbe_shapefile_for_year(year: int) -> Path:
    if year <= 2012:
        return ROOT / "data/census/SBE_PRECINCTS_20120901/SBE_PRECINCTS_09012012.shp"
    if year <= 2017:
        return ROOT / "data/census/SBE_PRECINCTS_20141016/PRECINCTS.shp"
    if year <= 2021:
        return ROOT / "data/census/SBE_PRECINCTS_20201018/SBE_PRECINCTS_20201018.shp"
    if year <= 2023:
        return ROOT / "data/census/SBE_PRECINCTS_20220118/SBE_PRECINCTS_20220118.shp"
    return ROOT / "data/census/SBE_PRECINCTS_20240723/SBE_PRECINCTS_20240723.shp"


def judicial_offices(src: pd.DataFrame) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for office in sorted(src["office"].dropna().astype(str).unique()):
        key = infer_office_key(office)
        if not key or not JUDICIAL_KEY_RE.match(key):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append((office.strip(), key))
    return out


def reaggregate_year(
    year: int,
    *,
    contests_dir: Path,
    contests_manifest: Path,
    dry_run: bool,
    rewrite_existing: bool,
    contest_types: set[str] | None = None,
) -> dict:
    results_csv = find_general_precinct_csv(year)
    print(f"\n=== {year} ===")
    print(f"results: {results_csv.as_posix()}")

    # Allow reload if this process already warmed the override cache earlier.
    builder._JUDICIAL_PARTY_OVERRIDE_CACHE = None
    lean = load_judicial_candidate_party_overrides()
    print(f"override candidates for {year}: {len(lean.get(year) or {})}")

    shp = sbe_shapefile_for_year(year)
    sbe_map = load_sbe_precinct_code_map(shp) if shp.exists() else {}
    clean_precinct_name._sbe_map = sbe_map  # type: ignore[attr-defined]
    build_auto_precinct_overrides._sbe_map = sbe_map  # type: ignore[attr-defined]

    src = pd.read_csv(results_csv, dtype=str, low_memory=False)
    match_crosswalk = resolve_vintage_match_crosswalk(
        year, fallback=ROOT / "data/crosswalks/block20_to_onemap_2025.csv"
    )
    if not match_crosswalk.exists():
        raise FileNotFoundError(f"Match crosswalk not found: {match_crosswalk}")
    print(f"match crosswalk: {match_crosswalk.as_posix()}")

    xw = pd.read_csv(match_crosswalk, dtype=str, low_memory=False)
    pid_col = "precinct_id" if "precinct_id" in xw.columns else xw.columns[0]
    matched_precincts = set(xw[pid_col].astype(str).str.strip().str.upper().unique())
    src_precinct_ids = (
        src["county"].astype(str).str.strip().str.upper()
        + " - "
        + src["precinct"].astype(str).str.strip().str.upper()
    )
    auto_overrides = build_auto_precinct_overrides(src_precinct_ids, matched_precincts)
    manual_overrides = load_precinct_overrides(
        ROOT / "data/mappings/precinct_key_overrides.csv", year
    )
    precinct_overrides = {**auto_overrides, **manual_overrides}

    written = 0
    skipped_uncontested = 0
    skipped_existing = 0
    skipped_empty = 0
    entries: list[dict] = []

    for office, contest_type in judicial_offices(src):
        if contest_types and contest_type not in contest_types:
            continue
        contest_file = contests_dir / f"{contest_type}_{year}.json"
        if contest_file.exists() and not rewrite_existing:
            print(f"  skip existing {contest_file.name}")
            skipped_existing += 1
            continue

        print(f"  build {office} -> {contest_type}")
        precinct_party, dem_candidate, rep_candidate = build_precinct_party_votes(
            src, office, precinct_overrides=precinct_overrides, election_year=year
        )
        if precinct_party.empty:
            print("    empty precinct party votes")
            skipped_empty += 1
            continue

        payload = build_precinct_contest_payload(
            year=year,
            contest_type=contest_type,
            office_label=office,
            nongeo_allocation_mode="precinct_candidate",
            precinct_party=precinct_party,
            dem_candidate=dem_candidate,
            rep_candidate=rep_candidate,
        )
        meta = payload.get("meta") or {}
        contested = bool(meta.get("major_party_contested"))
        dem_total = int(meta.get("dem_total", 0) or 0)
        rep_total = int(meta.get("rep_total", 0) or 0)
        other_total = int(meta.get("other_total", 0) or 0)
        print(
            f"    candidates {dem_candidate!r} / {rep_candidate!r} "
            f"D/R/O={dem_total}/{rep_total}/{other_total} contested={contested}"
        )
        if not contested:
            # Drop any previously written uncontested judicial slice for this key/year.
            if contest_file.exists() and not dry_run:
                contest_file.unlink()
                print(f"    removed uncontested {contest_file.name}")
            skipped_uncontested += 1
            continue

        if dry_run:
            print(f"    dry-run would write {contest_file.name} ({len(payload.get('rows') or [])} rows)")
            written += 1
            continue

        contests_dir.mkdir(parents=True, exist_ok=True)
        contest_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        entry = build_contests_manifest_entry(
            year=year,
            contest_type=contest_type,
            file_name=contest_file.name,
            payload=payload,
        )
        entries.append(entry)
        written += 1

    if entries and not dry_run:
        update_contests_manifest(contests_manifest, entries)

    # Purge uncontested judicial entries for this year from the live manifest.
    if not dry_run:
        purge_uncontested_judicial_manifest_year(contests_manifest, year, contest_types=contest_types)

    return {
        "year": year,
        "written": written,
        "skipped_uncontested": skipped_uncontested,
        "skipped_existing": skipped_existing,
        "skipped_empty": skipped_empty,
    }


def purge_uncontested_judicial_manifest_year(
    manifest_path: Path,
    year: int,
    *,
    contest_types: set[str] | None = None,
) -> None:
    if not manifest_path.exists():
        return
    try:
        base = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return
    files = list(base.get("files") or [])
    kept = []
    removed = 0
    for e in files:
        try:
            y = int(e.get("year"))
            ct = str(e.get("contest_type") or "")
        except Exception:
            kept.append(e)
            continue
        if contest_types and ct not in contest_types:
            kept.append(e)
            continue
        if y != int(year) or not JUDICIAL_KEY_RE.match(ct):
            kept.append(e)
            continue
        dem = int(e.get("dem_total", 0) or 0)
        rep = int(e.get("rep_total", 0) or 0)
        contested = e.get("major_party_contested")
        if contested is None:
            contested = dem > 0 and rep > 0
        if not contested:
            removed += 1
            continue
        kept.append(e)
    if removed:
        kept.sort(key=lambda x: (int(x.get("year", 0) or 0), str(x.get("contest_type") or "")))
        manifest_path.write_text(
            json.dumps({"files": kept}, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  purged {removed} uncontested judicial manifest entries for {year}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Reaggregate pre-2018 judicial county/precinct contest slices with party overrides."
    )
    p.add_argument(
        "--years",
        default=",".join(str(y) for y in DEFAULT_YEARS),
        help="Comma-separated election years (default: 2008,2010,2012,2014,2016).",
    )
    p.add_argument("--contests-dir", type=Path, default=ROOT / "data/contests")
    p.add_argument("--contests-manifest", type=Path, default=ROOT / "data/contests/manifest.json")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--contest-types",
        default="",
        help="Optional comma-separated contest keys to rebuild within the selected years.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Do not overwrite contest JSON files that already exist.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    years: list[int] = []
    for part in str(args.years).split(","):
        part = part.strip()
        if not part:
            continue
        years.append(int(part))
    if not years:
        raise SystemExit("No years provided")

    # Touch overrides so a missing CSV fails fast.
    load_path = ROOT / "data/mappings/judicial_candidate_party_overrides.csv"
    if not load_path.exists():
        raise FileNotFoundError(load_path)

    summaries = []
    contest_types = {part.strip() for part in str(args.contest_types).split(",") if part.strip()} or None
    for year in years:
        summaries.append(
            reaggregate_year(
                year,
                contests_dir=Path(args.contests_dir),
                contests_manifest=Path(args.contests_manifest),
                dry_run=bool(args.dry_run),
                rewrite_existing=not bool(args.skip_existing),
                contest_types=contest_types,
            )
        )

    print("\n=== summary ===")
    for s in summaries:
        print(
            f"{s['year']}: wrote={s['written']} uncontested={s['skipped_uncontested']} "
            f"existing={s['skipped_existing']} empty={s['skipped_empty']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
