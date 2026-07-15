#!/usr/bin/env python3
"""Build district contests into a sandbox folder and compare margins to live layers.

Does not write to live atlas dirs (`data/district_contests`, `_2024_lines`, `_2026_lines`)
unless those paths are passed explicitly as --out-dir.

Default sandbox: `data/district_contests_agg`
Default compare baseline (by --lines):
  2022 -> `data/district_contests_existing_snapshot`
  2024 -> `data/district_contests_2024_lines_existing_snapshot`

Margins are the gate (vote totals need not match live). Optional --calibrate retunes
sandbox Dem/Rep/Other to DRA stats CSVs / live margin_pct while preserving shatter totals.

Examples:
  # Aggregate 2020 president (2022 lines) into the sandbox only
  python scripts/build_district_contests_agg_compare.py --build --years 2020 --contest-type-regex ^president$

  # Compare whatever is already in the sandbox to live
  python scripts/build_district_contests_agg_compare.py --compare-only

  # Build, calibrate margins, then compare
  python scripts/build_district_contests_agg_compare.py --build --calibrate --compare --years 2020
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "scripts" / "build_district_contests_from_batch_shatter.py"
CALIBRATOR = ROOT / "scripts" / "calibrate_district_contests_agg_to_live.py"

LINE_DEFAULTS: dict[str, dict[str, Path | int | str]] = {
    "2022": {
        "house": Path("data/tmp/block_assign_extract/SL 2022-4.csv"),
        "senate": Path("data/tmp/block_assign_extract/SL 2022-2.csv"),
        # Builder expects GEOID/CDFP — prefer extract CSV over census .txt if present.
        "cd": Path("data/tmp/block_assign_extract/NC_CD118.csv"),
        "allocation_year": 2022,
        "snapshot": Path("data/district_contests_existing_snapshot"),
        "live": Path("data/district_contests"),
    },
    "2024": {
        "house": Path("data/tmp/block_assign_extract_2024/SL_2024_4.csv"),
        "senate": Path("data/tmp/block_assign_extract_2024/SL_2024_2.csv"),
        "cd": Path("data/tmp/block_assign_extract_2024/NC_CD119.csv"),
        "allocation_year": 2024,
        "snapshot": Path("data/district_contests_2024_lines_existing_snapshot"),
        "live": Path("data/district_contests_2024_lines"),
    },
}


def parse_years(raw: str) -> list[int]:
    years: list[int] = []
    for token in str(raw or "").split(","):
        t = token.strip()
        if t:
            years.append(int(t))
    return sorted(set(years))


def discover_general_csv(data_dir: Path, year: int) -> Path | None:
    year_dir = data_dir / str(year)
    if not year_dir.exists():
        return None
    matches = sorted(year_dir.glob("**/*__nc__general__precinct.csv"))
    if not matches:
        return None
    november = [p for p in matches if p.name.startswith(f"{year}11")]
    if november:
        return max(november, key=lambda p: p.stat().st_size)
    return max(matches, key=lambda p: p.stat().st_size)


def rebuild_manifest(out_dir: Path) -> None:
    files: list[dict] = []
    for path in sorted(out_dir.glob("*_*_*.json")):
        if path.name == "manifest.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = payload.get("meta") or {}
        scope = str(payload.get("scope") or "")
        contest_type = str(payload.get("contest_type") or "")
        year = int(payload.get("year") or 0)
        results = (payload.get("general") or {}).get("results") or {}
        if not (scope and contest_type and year):
            continue
        files.append(
            {
                "year": year,
                "scope": scope,
                "contest_type": contest_type,
                "file": path.name,
                "districts": len(results),
                "district_lines_year": meta.get("district_lines_year"),
                "district_lines_label": meta.get("district_lines_label"),
            }
        )
    (out_dir / "manifest.json").write_text(
        json.dumps({"files": files}, indent=2) + "\n",
        encoding="utf-8",
    )


def build_year(
    *,
    year: int,
    lines_year: int,
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
    nongeo_allocation_mode: str,
    contest_type_regex: str,
    python_exe: str,
    dry_run: bool,
) -> int:
    cmd = [
        python_exe,
        str(BUILDER),
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
        "--nongeo-allocation-mode",
        nongeo_allocation_mode,
        "--district-lines-year",
        str(lines_year),
        "--district-lines-label",
        f"{lines_year} lines",
        "--office-source",
        "auto",
        "--auto-vintage-match",
    ]
    if contest_type_regex.strip():
        cmd.extend(["--contest-type-regex", contest_type_regex.strip()])

    # Resolve for logging (builder resolves again independently).
    try:
        from build_district_contests_from_batch_shatter import resolve_vintage_match_crosswalk

        resolved = resolve_vintage_match_crosswalk(year, fallback=crosswalk_csv)
        print(f"\n[build {year}] match map -> {resolved.as_posix()}")
    except Exception as exc:
        print(f"\n[build {year}] (could not preview match map: {exc})")
    print(f"[build {year}] -> {out_dir}")
    print(" ", " ".join(cmd))
    if dry_run:
        return 0
    return subprocess.run(cmd, check=False).returncode


def _margin_pct(row: dict) -> float | None:
    if row is None:
        return None
    if "margin_pct" in row and row["margin_pct"] is not None:
        try:
            return float(row["margin_pct"])
        except (TypeError, ValueError):
            pass
    dem = float(row.get("dem_votes") or 0)
    rep = float(row.get("rep_votes") or 0)
    tot = dem + rep
    if tot <= 0:
        return None
    return 100.0 * (dem - rep) / tot


def compare_dirs(
    agg_dir: Path,
    snapshot_dir: Path,
    *,
    contest_type_regex: str,
    years: set[int] | None,
    out_csv: Path,
    skip_csv: Path | None = None,
) -> pd.DataFrame:
    rx = re.compile(contest_type_regex) if contest_type_regex.strip() else None
    rows: list[dict] = []

    skip_keys: set[tuple[int, str, str]] = set()
    if skip_csv is not None and skip_csv.exists():
        try:
            from calibrate_district_contests_agg_to_live import load_snapshot_skip_keys

            skip_keys = load_snapshot_skip_keys(skip_csv)
        except Exception as exc:
            print(f"(could not load skip csv {skip_csv}: {exc})")

    agg_files = {p.name: p for p in agg_dir.glob("*_*_*.json") if p.name != "manifest.json"}
    snap_files = {p.name: p for p in snapshot_dir.glob("*_*_*.json") if p.name != "manifest.json"}
    names = sorted(set(agg_files) & set(snap_files))

    for name in names:
        try:
            a = json.loads(agg_files[name].read_text(encoding="utf-8"))
            s = json.loads(snap_files[name].read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"skip {name}: {exc}")
            continue

        year = int(a.get("year") or s.get("year") or 0)
        scope = str(a.get("scope") or s.get("scope") or "")
        contest_type = str(a.get("contest_type") or s.get("contest_type") or "")
        if years and year not in years:
            continue
        if rx and not rx.search(contest_type):
            continue
        skipped_trust = (year, scope, contest_type) in skip_keys

        a_res = (a.get("general") or {}).get("results") or {}
        s_res = (s.get("general") or {}).get("results") or {}
        districts = sorted(set(map(str, a_res)) | set(map(str, s_res)), key=lambda d: (len(d), d))

        def _get(res: dict, key: str) -> dict | None:
            if key in res:
                return res[key]
            if key.isdigit():
                for alt in (str(int(key)), key.zfill(2), key.zfill(3)):
                    if alt in res:
                        return res[alt]
            return None

        for dist in districts:
            ar = _get(a_res, dist)
            sr = _get(s_res, dist)
            amp = _margin_pct(ar) if isinstance(ar, dict) else None
            smp = _margin_pct(sr) if isinstance(sr, dict) else None
            rows.append(
                {
                    "file": name,
                    "year": year,
                    "scope": scope,
                    "contest_type": contest_type,
                    "district": dist,
                    "agg_dem": (ar or {}).get("dem_votes") if isinstance(ar, dict) else None,
                    "agg_rep": (ar or {}).get("rep_votes") if isinstance(ar, dict) else None,
                    "snap_dem": (sr or {}).get("dem_votes") if isinstance(sr, dict) else None,
                    "snap_rep": (sr or {}).get("rep_votes") if isinstance(sr, dict) else None,
                    "agg_margin_pct": amp,
                    "snap_margin_pct": smp,
                    "delta_margin_pp": (None if amp is None or smp is None else amp - smp),
                    "in_agg_only": sr is None,
                    "in_snap_only": ar is None,
                    "snapshot_untrusted": skipped_trust,
                }
            )

    df = pd.DataFrame(rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    if df.empty:
        print(f"No overlapping slices to compare under {agg_dir.name} vs {snapshot_dir.name}")
        return df

    keyed = df.dropna(subset=["delta_margin_pp"]).copy()
    if "snapshot_untrusted" in keyed.columns:
        gate_rows = keyed[~keyed["snapshot_untrusted"].astype(bool)].copy()
        skipped_n = int(keyed["snapshot_untrusted"].astype(bool).sum())
    else:
        gate_rows = keyed
        skipped_n = 0

    print(f"Compared {len(df):,} district-rows across {df['file'].nunique()} files")
    if skipped_n:
        print(f"Excluded {skipped_n:,} rows from gate (untrusted snapshot contests)")
    print(f"Wrote {out_csv}")
    gate: dict[str, float | bool] = {
        "mean_abs": float("nan"),
        "median": float("nan"),
        "max_abs": float("nan"),
        "passed": False,
    }
    if not gate_rows.empty:
        mean_abs = float(gate_rows["delta_margin_pp"].abs().mean())
        median = float(gate_rows["delta_margin_pp"].median())
        max_abs = float(gate_rows["delta_margin_pp"].abs().max())
        gate = {
            "mean_abs": mean_abs,
            "median": median,
            "max_abs": max_abs,
            "passed": bool(mean_abs <= 1.0 and max_abs <= 2.0),
        }
        print(
            f"margin delta pp (trusted): mean={gate_rows['delta_margin_pp'].mean():+.3f} "
            f"mean_abs={mean_abs:.3f} median={median:+.3f} max_abs={max_abs:.3f} "
            f"gate={'PASS' if gate['passed'] else 'FAIL'} (mean_abs<=1 & max_abs<=2)"
        )
        top = gate_rows.reindex(gate_rows["delta_margin_pp"].abs().sort_values(ascending=False).index).head(15)
        print("\nLargest |delta margin| districts (trusted snapshot):")
        for _, r in top.iterrows():
            print(
                f"  {r['year']} {r['scope']} {r['contest_type']} dist {r['district']}: "
                f"agg={r['agg_margin_pct']:+.2f} snap={r['snap_margin_pct']:+.2f} "
                f"delta={r['delta_margin_pp']:+.2f}"
            )
    df.attrs["gate"] = gate
    return df


def run_calibrate(
    *,
    agg_dir: Path,
    live_dir: Path,
    years: list[int],
    python_exe: str,
    dry_run: bool,
) -> int:
    cmd = [
        python_exe,
        str(CALIBRATOR),
        "--agg-dir",
        str(agg_dir),
        "--live-dir",
        str(live_dir),
        # Hybrid: DRA stats CSV when present, else snapshot, skip untrusted snapshot contests.
    ]
    if years:
        cmd.extend(["--years", ",".join(str(y) for y in years)])
    print(f"\n[calibrate hybrid] margins <- DRA stats | {live_dir} | shatter-keep skips")
    print(" ", " ".join(cmd))
    if dry_run:
        return 0
    if not CALIBRATOR.exists():
        raise FileNotFoundError(CALIBRATOR)
    return subprocess.run(cmd, check=False).returncode


def main() -> None:
    p = argparse.ArgumentParser(
        description="Sandbox district aggregation + margin compare vs live DRA-calibrated layers."
    )
    p.add_argument("--build", action="store_true", help="Run shatter builder into --out-dir")
    p.add_argument(
        "--calibrate",
        action="store_true",
        help="After build (or alone), retune sandbox margins to DRA stats / live margin_pct",
    )
    p.add_argument("--compare", action="store_true", help="Compare --out-dir to --snapshot-dir")
    p.add_argument(
        "--compare-only",
        action="store_true",
        help="Skip build; only compare existing sandbox to snapshot",
    )
    p.add_argument("--years", type=str, default="2020", help="Comma-separated years to build/filter")
    p.add_argument(
        "--contest-type-regex",
        type=str,
        default="",
        help="Contest filter for build + compare (empty = all contests in OE / overlapping snapshot)",
    )
    p.add_argument(
        "--lines",
        choices=sorted(LINE_DEFAULTS),
        default="2022",
        help="District assignment vintage for --build (default 2022 to match live 2022-line layers)",
    )
    p.add_argument("--out-dir", type=Path, default=Path("data/district_contests_agg"))
    p.add_argument(
        "--snapshot-dir",
        type=Path,
        default=None,
        help="Margin baseline (default: *_existing_snapshot for --lines)",
    )
    p.add_argument(
        "--live-dir",
        type=Path,
        default=None,
        help="Live layers used for margin calibration when no DRA stats CSV (default: live dir for --lines)",
    )
    p.add_argument(
        "--compare-csv",
        type=Path,
        default=Path("data/reports/district_margin_compare_agg_vs_existing_snapshot.csv"),
    )
    p.add_argument("--crosswalk-csv", type=Path, default=Path("data/crosswalks/block20_to_onemap_2025_12.csv"))
    p.add_argument("--vap-csv", type=Path, default=Path("data/census/block_vap_2020_nc.csv"))
    p.add_argument("--allocation-weights-json", type=Path, default=Path("data/mappings/allocation_weights.json"))
    p.add_argument("--precinct-overrides-csv", type=Path, default=Path("data/mappings/precinct_key_overrides.csv"))
    p.add_argument(
        "--nongeo-allocation-mode",
        choices=["precinct_candidate", "county_weights"],
        default="precinct_candidate",
    )
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--python-exe", type=str, default=sys.executable)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--house-file", type=Path, default=None)
    p.add_argument("--senate-file", type=Path, default=None)
    p.add_argument("--cd-file", type=Path, default=None)
    p.add_argument("--allocation-year", type=int, default=None)
    p.add_argument(
        "--skip-odd-years",
        action="store_true",
        help="Ignore odd-numbered election years in build, calibration, and comparison inputs.",
    )
    args = p.parse_args()

    do_build = bool(args.build) and not args.compare_only
    do_calibrate = bool(args.calibrate) and not args.compare_only
    do_compare = bool(args.compare or args.compare_only)
    if not do_build and not do_compare and not do_calibrate:
        # Default UX: build + calibrate + compare
        do_build = True
        do_calibrate = True
        do_compare = True

    years = parse_years(args.years)
    if args.skip_odd_years:
        years = [year for year in years if year % 2 == 0]
    line = LINE_DEFAULTS[args.lines]
    house = args.house_file or Path(str(line["house"]))
    senate = args.senate_file or Path(str(line["senate"]))
    cd = args.cd_file or Path(str(line["cd"]))
    alloc_year = int(args.allocation_year if args.allocation_year is not None else line["allocation_year"])
    snapshot_dir = Path(args.snapshot_dir) if args.snapshot_dir else Path(str(line["snapshot"]))
    live_dir = Path(args.live_dir) if args.live_dir else Path(str(line["live"]))

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if do_build:
        if not BUILDER.exists():
            raise FileNotFoundError(BUILDER)
        required = [
            args.crosswalk_csv,
            args.vap_csv,
            house,
            senate,
            cd,
            args.allocation_weights_json,
        ]
        missing = [str(x) for x in required if not Path(x).exists()]
        if missing:
            raise FileNotFoundError(
                "Missing build inputs (assignment extracts may need to be restored):\n"
                + "\n".join(missing)
            )

        failures: list[int] = []
        for year in years:
            csv_path = discover_general_csv(args.data_dir, year)
            if csv_path is None:
                print(f"[skip {year}] no OpenElections general precinct CSV under {args.data_dir / str(year)}")
                failures.append(year)
                continue
            rc = build_year(
                year=year,
                lines_year=int(args.lines),
                results_csv=csv_path,
                out_dir=args.out_dir,
                crosswalk_csv=args.crosswalk_csv,
                vap_csv=args.vap_csv,
                house_file=house,
                senate_file=senate,
                cd_file=cd,
                allocation_weights_json=args.allocation_weights_json,
                precinct_overrides_csv=args.precinct_overrides_csv,
                allocation_year=alloc_year,
                nongeo_allocation_mode=args.nongeo_allocation_mode,
                contest_type_regex=args.contest_type_regex,
                python_exe=args.python_exe,
                dry_run=args.dry_run,
            )
            if rc != 0:
                failures.append(year)
        if not args.dry_run:
            rebuild_manifest(args.out_dir)
        if failures:
            print(f"Build issues for years: {failures}")

    if do_calibrate:
        # Calibrate margins to existing_snapshot (DRA-calibrated baseline); preserve shatter totals.
        rc = run_calibrate(
            agg_dir=args.out_dir,
            live_dir=snapshot_dir,
            years=years,
            python_exe=args.python_exe,
            dry_run=args.dry_run,
        )
        if rc != 0:
            raise SystemExit(rc)

    if do_compare:
        if not snapshot_dir.exists():
            raise FileNotFoundError(f"Snapshot dir missing: {snapshot_dir}")
        df = compare_dirs(
            args.out_dir,
            snapshot_dir,
            contest_type_regex=args.contest_type_regex,
            years=set(years) if years else None,
            out_csv=args.compare_csv,
            skip_csv=Path("data/mappings/snapshot_margin_trust_skip.csv"),
        )
        gate = df.attrs.get("gate") or {}
        if gate and not gate.get("passed", False) and not df.empty:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
