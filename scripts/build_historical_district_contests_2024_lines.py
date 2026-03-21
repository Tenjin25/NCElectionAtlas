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
import concurrent.futures
import json
import shutil
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


def rebuild_manifest(out_dir: Path) -> None:
    manifest: list[dict] = []
    for p in sorted(out_dir.glob("*.json")):
        if p.name == "manifest.json":
            continue
        parts = p.stem.split("_")
        if len(parts) < 3:
            continue
        if parts[0] == "state" and len(parts) >= 4:
            scope = "_".join(parts[0:2])
            contest_type = "_".join(parts[2:-1])
        else:
            scope = parts[0]
            contest_type = "_".join(parts[1:-1])
        try:
            year = int(parts[-1])
        except ValueError:
            continue

        districts = 0
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            districts = len((((payload.get("general") or {}).get("results")) or {}))
        except Exception:
            districts = 0

        manifest.append(
            {
                "year": year,
                "scope": scope,
                "contest_type": contest_type,
                "file": p.name,
                "districts": districts,
            }
        )
    manifest.sort(key=lambda x: (x["year"], x["scope"], x["contest_type"]))
    (out_dir / "manifest.json").write_text(json.dumps({"files": manifest}, indent=2), encoding="utf-8")


def merge_parallel_outputs(*, planned_years: list[int], tmp_root: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for year in planned_years:
        year_dir = tmp_root / f"year_{year}"
        if not year_dir.exists():
            continue
        for src in year_dir.glob(f"*_{year}.json"):
            if src.name == "manifest.json":
                continue
            shutil.copy2(src, out_dir / src.name)
            copied += 1
    rebuild_manifest(out_dir)
    print(f"Merged {copied} year-slice files into {out_dir}")


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
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Parallel year workers. Use >1 for faster builds (safe merge mode).",
    )
    parser.add_argument(
        "--tmp-root",
        type=Path,
        default=Path("data/tmp/historical_2024_lines_parallel"),
        help="Temporary root for per-year outputs when --jobs > 1.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep per-year temp directories after a parallel run.",
    )
    parser.add_argument(
        "--skip-odd-years",
        action="store_true",
        help="Skip odd years (often much less useful for statewide historical comparisons).",
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
    if args.skip_odd_years:
        years = [y for y in years if y % 2 == 0]
    years = sorted(set(y for y in years if y > 0))
    if not years:
        raise SystemExit("No years selected.")
    if args.jobs < 1:
        raise SystemExit("--jobs must be >= 1")

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

    run_out_dir_by_year: dict[int, Path] = {}
    if args.jobs > 1:
        args.tmp_root.mkdir(parents=True, exist_ok=True)
        for year, _csv_path in planned:
            year_out = args.tmp_root / f"year_{year}"
            if year_out.exists() and not args.dry_run:
                shutil.rmtree(year_out, ignore_errors=True)
            year_out.mkdir(parents=True, exist_ok=True)
            run_out_dir_by_year[year] = year_out

    failures: list[int] = []
    if args.jobs == 1:
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
    else:
        print(f"Running in parallel with {args.jobs} jobs (isolated per-year outputs).")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            future_to_year: dict[concurrent.futures.Future[int], int] = {}
            for year, csv_path in planned:
                out_dir = run_out_dir_by_year[year]
                future = pool.submit(
                    build_year,
                    python_exe=args.python_exe,
                    builder_script=builder_script,
                    year=year,
                    results_csv=csv_path,
                    out_dir=out_dir,
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
                future_to_year[future] = year
            for future in concurrent.futures.as_completed(future_to_year):
                year = future_to_year[future]
                try:
                    rc = int(future.result())
                except Exception as exc:
                    print(f"[{year}] failed with exception: {exc}")
                    rc = 1
                if rc != 0:
                    failures.append(year)

    if failures:
        raise SystemExit(f"Build failed for year(s): {', '.join(str(y) for y in failures)}")

    if args.jobs > 1 and not args.dry_run:
        merge_parallel_outputs(
            planned_years=[y for y, _ in planned],
            tmp_root=args.tmp_root,
            out_dir=args.out_dir,
        )
        if not args.keep_temp:
            shutil.rmtree(args.tmp_root, ignore_errors=True)

    print("\nHistorical 2024-lines district slice build complete.")
    print(f"Updated directory: {args.out_dir}")


if __name__ == "__main__":
    main()
