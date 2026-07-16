#!/usr/bin/env python3
"""Reallocate live district contest votes to snapshot margins.

Keeps each district's live `total_votes` (and writes dem/rep/other that sum to it).
Target margins come from matching files in an existing_snapshot folder.

Typical usage (2022-line congressional contests for 2024):

  python scripts/reallocate_live_district_votes_to_snapshot_margins.py \\
    --live-dir data/district_contests \\
    --snapshot-dir data/district_contests_existing_snapshot \\
    --scope congressional \\
    --years 2024 \\
    --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from calibrate_district_slices_to_stats_margins import (  # noqa: E402
    StatsRow,
    calculate_competitiveness,
    normalize_district_id,
    solve_votes_for_margin,
)


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def results_map(payload: dict[str, Any]) -> dict[str, Any]:
    general = payload.get("general") or {}
    results = general.get("results") if isinstance(general, dict) else None
    if not isinstance(results, dict):
        raise ValueError("missing general.results")
    return results


def snapshot_margin_targets(snapshot_payload: dict[str, Any], *, precision: int) -> dict[str, StatsRow]:
    out: dict[str, StatsRow] = {}
    for raw_id, row in results_map(snapshot_payload).items():
        district = normalize_district_id(raw_id)
        if not district or not isinstance(row, dict):
            continue
        dem = float(row.get("dem_votes") or 0)
        rep = float(row.get("rep_votes") or 0)
        other = float(row.get("other_votes") or 0)
        total = float(row.get("total_votes") or (dem + rep + other))
        if total <= 0:
            continue
        if "margin_pct" in row and row.get("margin_pct") is not None:
            target_margin_pct = float(row["margin_pct"])
        else:
            target_margin_pct = ((rep - dem) / total) * 100.0
        dem_share = dem / total
        rep_share = rep / total
        other_share = max(0.0, 1.0 - dem_share - rep_share)
        out[district] = StatsRow(
            district=district,
            dem_share=dem_share,
            rep_share=rep_share,
            other_share=other_share,
            target_margin_pct=target_margin_pct,
            target_margin_display=round(target_margin_pct, precision),
            source_total_votes=int(round(total)),
        )
    return out


def reallocate_live_file(
    live_path: Path,
    snapshot_path: Path,
    *,
    precision: int,
    write: bool,
) -> dict[str, Any]:
    raw_text = live_path.read_text(encoding="utf-8")
    live_payload = json.loads(raw_text)
    snapshot_payload = load_payload(snapshot_path)
    targets = snapshot_margin_targets(snapshot_payload, precision=precision)
    results = results_map(live_payload)

    calibrated = 0
    exact = 0
    missing_targets = 0
    misses: list[dict[str, Any]] = []
    total_preserved = True

    for raw_id, row in results.items():
        district = normalize_district_id(raw_id)
        if not district or not isinstance(row, dict):
            continue
        stats = targets.get(district)
        if not stats:
            missing_targets += 1
            continue

        old_dem = int(row.get("dem_votes") or 0)
        old_rep = int(row.get("rep_votes") or 0)
        old_oth = int(row.get("other_votes") or 0)
        total_votes = int(row.get("total_votes") or (old_dem + old_rep + old_oth) or 0)
        if total_votes <= 0:
            continue

        solved = solve_votes_for_margin(
            total_votes=total_votes,
            stats=stats,
            precision=precision,
            margin_basis="total",
            exact_rounded_margin=True,
            other_search_radius=50,
            margin_search_radius=500,
        )
        if (solved.dem_votes + solved.rep_votes + solved.other_votes) != total_votes:
            total_preserved = False

        display_delta = abs(solved.margin_pct - stats.target_margin_display)
        if display_delta == 0:
            exact += 1
        else:
            misses.append(
                {
                    "district": district,
                    "target_margin_pct": stats.target_margin_display,
                    "output_margin_pct": solved.margin_pct,
                    "delta": round(display_delta, precision + 2),
                }
            )

        if write:
            row["dem_votes"] = solved.dem_votes
            row["rep_votes"] = solved.rep_votes
            row["other_votes"] = solved.other_votes
            row["total_votes"] = total_votes
            row["margin"] = solved.margin
            row["margin_pct"] = solved.margin_pct
            row["winner"] = (
                "REP"
                if solved.rep_votes > solved.dem_votes
                else ("DEM" if solved.dem_votes > solved.rep_votes else "TIE")
            )
            color = calculate_competitiveness(solved.margin_pct)
            if isinstance(row.get("competitiveness"), dict):
                row["competitiveness"]["color"] = color
            else:
                row["competitiveness"] = {"color": color}

        calibrated += 1

    if write:
        meta = live_payload.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["margin_calibrated_to"] = "existing_snapshot_margins"
            meta["margin_calibration_mode"] = "preserve_live_total_votes"
            meta["margin_calibration_snapshot"] = str(snapshot_path).replace("\\", "/")
        was_pretty = ("\n" in raw_text.strip()) and (len(raw_text.strip().splitlines()) > 1)
        if was_pretty:
            out_text = json.dumps(live_payload, indent=2, ensure_ascii=False) + "\n"
        else:
            out_text = json.dumps(live_payload, separators=(",", ":"), ensure_ascii=False)
        live_path.write_text(out_text, encoding="utf-8")

    return {
        "file": live_path.name,
        "calibrated": calibrated,
        "exact_rounded_margin_matches": exact,
        "missing_snapshot_districts": missing_targets,
        "miss_count": len(misses),
        "misses": misses[:10],
        "total_votes_preserved": total_preserved,
        "wrote": write,
    }


def iter_live_files(
    live_dir: Path,
    *,
    scope: str | None,
    years: set[int] | None,
    contest_glob: str,
) -> list[Path]:
    files = sorted(live_dir.glob(contest_glob))
    out: list[Path] = []
    for path in files:
        if path.name == "manifest.json":
            continue
        try:
            payload = load_payload(path)
        except Exception:
            continue
        year = int(payload.get("year") or 0)
        file_scope = str(payload.get("scope") or "").strip().lower()
        if years is not None and year not in years:
            continue
        if scope and file_scope != scope.strip().lower():
            # Also allow filename prefix filter when scope meta is missing/odd.
            if not path.name.lower().startswith(f"{scope.strip().lower()}_"):
                continue
        out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-dir", type=Path, default=ROOT / "data" / "district_contests")
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=ROOT / "data" / "district_contests_existing_snapshot",
    )
    parser.add_argument("--scope", default="congressional", help="Scope filter (default: congressional)")
    parser.add_argument("--years", default="2024", help="Comma-separated years (default: 2024)")
    parser.add_argument("--glob", default="*.json", dest="contest_glob", help="Filename glob inside live-dir")
    parser.add_argument("--precision", type=int, default=2)
    parser.add_argument("--write", action="store_true", help="Write reallocated live JSON files")
    parser.add_argument("--summary-json", type=Path, default=None)
    args = parser.parse_args()

    years = {int(part.strip()) for part in str(args.years).split(",") if part.strip()}
    live_dir = args.live_dir if args.live_dir.is_absolute() else ROOT / args.live_dir
    snapshot_dir = args.snapshot_dir if args.snapshot_dir.is_absolute() else ROOT / args.snapshot_dir

    if not live_dir.exists():
        raise SystemExit(f"Live dir missing: {live_dir}")
    if not snapshot_dir.exists():
        raise SystemExit(f"Snapshot dir missing: {snapshot_dir}")

    live_files = iter_live_files(
        live_dir,
        scope=args.scope,
        years=years,
        contest_glob=args.contest_glob,
    )
    if not live_files:
        raise SystemExit("No matching live contest files found")

    summaries: list[dict[str, Any]] = []
    for live_path in live_files:
        snapshot_path = snapshot_dir / live_path.name
        if not snapshot_path.exists():
            summaries.append(
                {
                    "file": live_path.name,
                    "error": f"missing snapshot: {snapshot_path}",
                    "wrote": False,
                }
            )
            continue
        summaries.append(
            reallocate_live_file(
                live_path,
                snapshot_path,
                precision=args.precision,
                write=bool(args.write),
            )
        )

    calibrated = sum(int(s.get("calibrated") or 0) for s in summaries)
    exact = sum(int(s.get("exact_rounded_margin_matches") or 0) for s in summaries)
    misses = sum(int(s.get("miss_count") or 0) for s in summaries)
    errors = [s for s in summaries if s.get("error")]

    print(
        json.dumps(
            {
                "mode": "write" if args.write else "audit",
                "live_dir": str(live_dir),
                "snapshot_dir": str(snapshot_dir),
                "files": len(summaries),
                "calibrated_districts": calibrated,
                "exact_margin_matches": exact,
                "margin_misses": misses,
                "errors": len(errors),
                "summaries": summaries,
            },
            indent=2,
        )
    )

    if args.summary_json:
        out = args.summary_json if args.summary_json.is_absolute() else ROOT / args.summary_json
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summaries, indent=2), encoding="utf-8")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
