#!/usr/bin/env python3
from __future__ import annotations

"""
Build district contest JSON slices for historical years on 2024 district lines.

This is a thin orchestrator around:
  scripts/build_district_contests_from_batch_shatter.py

It points that builder at 2024 assignment files:
  - data/tmp/block_assign_extract_2024/SL_2024_4.csv   (State House)
  - data/tmp/block_assign_extract_2024/SL_2024_2.csv   (State Senate)
  - data/tmp/block_assign_extract_2024/NC_CD119.csv    (Congressional)

Example:
  python scripts/build_historical_district_contests_2024_lines.py --min-year 2000 --max-year 2022
"""

import argparse
import subprocess
import sys
from pathlib import Path


def parse_years(raw: str) -> list[int]:
    years: list[int] = []
    for token in str(raw or "").split(","):
        t = token.strip()
        if not t:
            continue
        years.append(int(t))
    return sorted(set(years))


def discover_general_csv_for_year(data_dir: Path, year: int) -> Path | None:
    year_dir = data_dir / str(year)
    if not year_dir.exists():
        return None
    matches = sorted(year_dir.glob("**/*__nc__general__precinct.csv"))
    if not matches:
        return None
    # Pick the largest file as best proxy for the statewide November general file.
    return max(matches, key=lambda p: p.stat().st_size)


def build_year(
    *,
    python_exe: str,
    builder_script: Path,
    year: int,
    results_csv: Path,
    out_dir: Path,
    crosswalk_csv: Path,
    vap_csv: Path,
    house_file: Path,
    senate_file: Path,
    cd_file: Path,
    allocation_weights_json: Path,
    precinct_overrides_csv: Path,
    allocation_year: int,
    min_county_share: float,
    nongeo_allocation_mode: str,
    contest_type_regex: str,
    verbose_builder: bool,
    dry_run: bool,
) -> int:
    cmd = [
        python_exe,
        str(builder_script),
        "--year",
        str(year),
        "--results-csv",
        str(results_csv),
        "--district-contests-dir",
        str(out_dir),
        "--crosswalk-csv",
        str(crosswalk_csv),
        "--vap-csv",
        str(vap_csv),
        "--house-file",
        str(house_file),
        "--senate-file",
        str(senate_file),
        "--cd-file",
        str(cd_file),
        "--allocation-weights-json",
        str(allocation_weights_json),
        "--precinct-overrides-csv",
        str(precinct_overrides_csv),
        "--allocation-year",
        str(allocation_year),
        "--min-county-share",
        str(min_county_share),
        "--nongeo-allocation-mode",
        nongeo_allocation_mode,
        "--office-source",
        "auto",
    ]
    if contest_type_regex.strip():
        cmd.extend(["--contest-type-regex", contest_type_regex.strip()])

    print(f"\n[{year}] {results_csv}")
    if dry_run:
        print("DRY RUN:", " ".join(cmd))
        return 0
    if verbose_builder:
        return subprocess.run(cmd, check=False).returncode

    proc = subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode == 0:
        print(f"[{year}] done")
    else:
        err = (proc.stderr or "").strip()
        tail = "\n".join(err.splitlines()[-20:]) if err else "(no stderr)"
        print(f"[{year}] failed")
        print(tail)
    return proc.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build historical district contest slices (2000-2022) on 2024 lines."
    )
    parser.add_argument("--min-year", type=int, default=2000)
    parser.add_argument("--max-year", type=int, default=2022)
    parser.add_argument(
        "--years",
        type=str,
        default="",
        help="Optional comma-separated year list (overrides min/max). Example: 2000,2004,2008",
    )
    parser.add_argument(
        "--contest-type-regex",
        type=str,
        default="",
        help="Optional filter passed through to build_district_contests_from_batch_shatter.py",
    )
    parser.add_argument("--python-exe", type=str, default=sys.executable)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/district_contests_2024_lines"))
    parser.add_argument("--crosswalk-csv", type=Path, default=Path("data/crosswalks/block20_to_precinct.csv"))
    parser.add_argument("--vap-csv", type=Path, default=Path("data/census/block_vap_2020_nc.csv"))
    parser.add_argument(
        "--house-file",
        type=Path,
        default=Path("data/tmp/block_assign_extract_2024/SL_2024_4.csv"),
    )
    parser.add_argument(
        "--senate-file",
        type=Path,
        default=Path("data/tmp/block_assign_extract_2024/SL_2024_2.csv"),
    )
    parser.add_argument(
        "--cd-file",
        type=Path,
        default=Path("data/tmp/block_assign_extract_2024/NC_CD119.csv"),
    )
    parser.add_argument(
        "--allocation-weights-json",
        type=Path,
        default=Path("data/mappings/allocation_weights.json"),
    )
    parser.add_argument(
        "--precinct-overrides-csv",
        type=Path,
        default=Path("data/mappings/precinct_key_overrides.csv"),
    )
    parser.add_argument(
        "--allocation-year",
        type=int,
        default=2024,
        help="Year key used in allocation_weights.json for share overrides.",
    )
    parser.add_argument("--min-county-share", type=float, default=0.01)
    parser.add_argument(
        "--nongeo-allocation-mode",
        choices=["precinct_candidate", "county_weights"],
        default="precinct_candidate",
    )
    parser.add_argument(
        "--verbose-builder",
        action="store_true",
        help="Stream full output from the underlying per-year builder.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    builder_script = root / "scripts" / "build_district_contests_from_batch_shatter.py"
    if not builder_script.exists():
        raise FileNotFoundError(f"Missing builder script: {builder_script}")

    required = [
        args.crosswalk_csv,
        args.vap_csv,
        args.house_file,
        args.senate_file,
        args.cd_file,
        args.allocation_weights_json,
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    years = parse_years(args.years) if str(args.years).strip() else list(range(args.min_year, args.max_year + 1))
    years = sorted(set(y for y in years if y > 0))
    if not years:
        raise SystemExit("No years selected.")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    planned: list[tuple[int, Path]] = []
    skipped: list[int] = []
    for year in years:
        csv_path = discover_general_csv_for_year(args.data_dir, year)
        if csv_path is None:
            skipped.append(year)
            continue
        planned.append((year, csv_path))

    if not planned:
        raise SystemExit("No yearly general-election CSV files found for requested years.")

    print(f"Using builder: {builder_script}")
    print(f"Output dir: {args.out_dir}")
    print(f"Years queued: {', '.join(str(y) for y, _ in planned)}")
    if skipped:
        print(f"Years skipped (no general precinct CSV found): {', '.join(str(y) for y in skipped)}")

    failures: list[int] = []
    for year, csv_path in planned:
        rc = build_year(
            python_exe=args.python_exe,
            builder_script=builder_script,
            year=year,
            results_csv=csv_path,
            out_dir=args.out_dir,
            crosswalk_csv=args.crosswalk_csv,
            vap_csv=args.vap_csv,
            house_file=args.house_file,
            senate_file=args.senate_file,
            cd_file=args.cd_file,
            allocation_weights_json=args.allocation_weights_json,
            precinct_overrides_csv=args.precinct_overrides_csv,
            allocation_year=args.allocation_year,
            min_county_share=args.min_county_share,
            nongeo_allocation_mode=args.nongeo_allocation_mode,
            contest_type_regex=args.contest_type_regex,
            verbose_builder=args.verbose_builder,
            dry_run=args.dry_run,
        )
        if rc != 0:
            failures.append(year)

    if failures:
        raise SystemExit(f"Build failed for year(s): {', '.join(str(y) for y in failures)}")

    print("\nHistorical 2024-lines district slice build complete.")
    print(f"Updated directory: {args.out_dir}")


if __name__ == "__main__":
    main()
