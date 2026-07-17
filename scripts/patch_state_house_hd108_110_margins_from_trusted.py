#!/usr/bin/env python3
"""Audit and patch HD-108/109/110 margins on 2022-line State House slices.

Uses trusted margins from data/district_contests_dra_review (fallback:
data/district_contests_2024_lines) while preserving each district's live
total_votes.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
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

TARGET_DISTRICTS = ("108", "109", "110")


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def results_map(payload: dict[str, Any]) -> dict[str, Any]:
    general = payload.get("general") or {}
    results = general.get("results") if isinstance(general, dict) else None
    if not isinstance(results, dict):
        raise ValueError("missing general.results")
    return results


def signed_margin_pct(row: dict[str, Any]) -> float | None:
    dem = float(row.get("dem_votes") or 0)
    rep = float(row.get("rep_votes") or 0)
    other = float(row.get("other_votes") or 0)
    total = float(row.get("total_votes") or (dem + rep + other))
    if total <= 0:
        return None
    if row.get("margin_pct") is not None:
        return float(row["margin_pct"])
    return ((rep - dem) / total) * 100.0


def trusted_path_for(name: str, trusted_dirs: list[Path]) -> Path | None:
    for directory in trusted_dirs:
        path = directory / name
        if path.exists():
            return path
    return None


def build_targets(trusted_payload: dict[str, Any], *, precision: int) -> dict[str, StatsRow]:
    out: dict[str, StatsRow] = {}
    for raw_id, row in results_map(trusted_payload).items():
        district = normalize_district_id(raw_id)
        if district not in TARGET_DISTRICTS or not isinstance(row, dict):
            continue
        dem = float(row.get("dem_votes") or 0)
        rep = float(row.get("rep_votes") or 0)
        other = float(row.get("other_votes") or 0)
        total = float(row.get("total_votes") or (dem + rep + other))
        if total <= 0:
            continue
        target_margin_pct = signed_margin_pct(row)
        if target_margin_pct is None:
            continue
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


def patch_file(
    live_path: Path,
    trusted_path: Path,
    *,
    precision: int,
    write: bool,
    min_abs_delta: float,
) -> dict[str, Any]:
    raw_text = live_path.read_text(encoding="utf-8")
    live_payload = json.loads(raw_text)
    trusted_payload = load_payload(trusted_path)
    targets = build_targets(trusted_payload, precision=precision)
    results = results_map(live_payload)

    entries: list[dict[str, Any]] = []
    changed = 0

    for district in TARGET_DISTRICTS:
        row = results.get(district)
        stats = targets.get(district)
        if not isinstance(row, dict) or not stats:
            entries.append(
                {
                    "district": district,
                    "status": "missing",
                    "has_live": isinstance(row, dict),
                    "has_trusted": bool(stats),
                }
            )
            continue

        before = {
            "dem_votes": int(row.get("dem_votes") or 0),
            "rep_votes": int(row.get("rep_votes") or 0),
            "other_votes": int(row.get("other_votes") or 0),
            "total_votes": int(
                row.get("total_votes")
                or (
                    int(row.get("dem_votes") or 0)
                    + int(row.get("rep_votes") or 0)
                    + int(row.get("other_votes") or 0)
                )
            ),
            "margin": row.get("margin"),
            "margin_pct": row.get("margin_pct"),
            "winner": row.get("winner"),
            "competitiveness": row.get("competitiveness"),
        }
        live_margin = signed_margin_pct(row)
        delta = None if live_margin is None else abs(live_margin - stats.target_margin_pct)
        if delta is None or delta < min_abs_delta:
            entries.append(
                {
                    "district": district,
                    "status": "skip_small_delta",
                    "live_margin_pct": None if live_margin is None else round(live_margin, precision),
                    "trusted_margin_pct": stats.target_margin_display,
                    "abs_delta": None if delta is None else round(delta, precision),
                }
            )
            continue

        total_votes = before["total_votes"]
        solved = solve_votes_for_margin(
            total_votes=total_votes,
            stats=stats,
            precision=precision,
            margin_basis="total",
            exact_rounded_margin=True,
            other_search_radius=50,
            margin_search_radius=500,
        )
        after = {
            "dem_votes": solved.dem_votes,
            "rep_votes": solved.rep_votes,
            "other_votes": solved.other_votes,
            "total_votes": total_votes,
            "margin": solved.margin,
            "margin_pct": solved.margin_pct,
            "winner": (
                "REP"
                if solved.rep_votes > solved.dem_votes
                else ("DEM" if solved.dem_votes > solved.rep_votes else "TIE")
            ),
            "competitiveness": {"color": calculate_competitiveness(solved.margin_pct)},
        }

        if write:
            row["dem_votes"] = after["dem_votes"]
            row["rep_votes"] = after["rep_votes"]
            row["other_votes"] = after["other_votes"]
            row["total_votes"] = after["total_votes"]
            row["margin"] = after["margin"]
            row["margin_pct"] = after["margin_pct"]
            row["winner"] = after["winner"]
            if isinstance(row.get("competitiveness"), dict):
                row["competitiveness"]["color"] = after["competitiveness"]["color"]
            else:
                row["competitiveness"] = after["competitiveness"]

        changed += 1
        entries.append(
            {
                "district": district,
                "status": "patched",
                "live_margin_pct": round(live_margin, precision),
                "trusted_margin_pct": stats.target_margin_display,
                "abs_delta": round(delta, precision),
                "before": before,
                "after": after,
            }
        )

    if write and changed:
        meta = live_payload.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["margin_calibration_mode"] = "preserve_live_total_votes"
            meta["margin_calibration_target_districts"] = list(TARGET_DISTRICTS)
            meta["margin_calibration_snapshot"] = str(trusted_path).replace("\\", "/")
            meta["margin_calibrated_to"] = "dra_review_or_2024_lines_hd108_110"
        was_pretty = ("\n" in raw_text.strip()) and (len(raw_text.strip().splitlines()) > 1)
        if was_pretty:
            out_text = json.dumps(live_payload, indent=2, ensure_ascii=False) + "\n"
        else:
            out_text = json.dumps(live_payload, separators=(",", ":"), ensure_ascii=False)
        live_path.write_text(out_text, encoding="utf-8")

    max_delta = 0.0
    for entry in entries:
        if entry.get("status") == "patched":
            max_delta = max(max_delta, float(entry.get("abs_delta") or 0))
        elif entry.get("status") == "skip_small_delta":
            max_delta = max(max_delta, float(entry.get("abs_delta") or 0))

    return {
        "file": str(live_path.as_posix()).replace(str(ROOT.as_posix()) + "/", ""),
        "trusted": str(trusted_path.as_posix()).replace(str(ROOT.as_posix()) + "/", ""),
        "changed_districts": changed,
        "max_abs_delta": round(max_delta, precision),
        "wrote": bool(write and changed),
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-dir", type=Path, default=ROOT / "data" / "district_contests")
    parser.add_argument(
        "--trusted-dirs",
        default="data/district_contests_dra_review,data/district_contests_2024_lines",
        help="Comma-separated trusted margin sources (first hit wins)",
    )
    parser.add_argument("--glob", default="state_house_*.json", dest="contest_glob")
    parser.add_argument(
        "--years",
        default="",
        help="Optional comma-separated years to include (default: all). Example: 2000,2004,2008,2012,2016",
    )
    parser.add_argument(
        "--exclude-years",
        default="2020,2022,2024",
        help="Comma-separated years to skip (default: 2020,2022,2024 — already trusted on live)",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Optional comma-separated filenames to include (e.g. state_house_governor_2016.json)",
    )
    parser.add_argument("--min-abs-delta", type=float, default=0.75, help="Skip tiny margin gaps")
    parser.add_argument("--precision", type=int, default=2)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=ROOT / "data/reports/state_house_hd108_110_remaining_margin_calibration_summary.json",
    )
    args = parser.parse_args()

    live_dir = args.live_dir if args.live_dir.is_absolute() else ROOT / args.live_dir
    trusted_dirs = [
        (ROOT / part.strip()) if not Path(part.strip()).is_absolute() else Path(part.strip())
        for part in str(args.trusted_dirs).split(",")
        if part.strip()
    ]
    years = {int(part.strip()) for part in str(args.years).split(",") if part.strip()}
    exclude_years = {int(part.strip()) for part in str(args.exclude_years).split(",") if part.strip()}
    only = {part.strip() for part in str(args.only).split(",") if part.strip()}

    files = sorted(live_dir.glob(args.contest_glob))
    summaries: list[dict[str, Any]] = []
    for live_path in files:
        if live_path.name == "manifest.json":
            continue
        if only and live_path.name not in only:
            continue
        try:
            live_year = int(load_payload(live_path).get("year") or 0)
        except Exception:
            live_year = 0
        if years and live_year not in years:
            continue
        if exclude_years and live_year in exclude_years:
            continue
        trusted = trusted_path_for(live_path.name, trusted_dirs)
        if not trusted:
            summaries.append({"file": live_path.name, "error": "missing trusted source"})
            continue
        try:
            summaries.append(
                patch_file(
                    live_path,
                    trusted,
                    precision=args.precision,
                    write=bool(args.write),
                    min_abs_delta=float(args.min_abs_delta),
                )
            )
        except Exception as exc:  # noqa: BLE001
            summaries.append({"file": live_path.name, "error": str(exc)})

    actionable = [
        s
        for s in summaries
        if int(s.get("changed_districts") or 0) > 0 or float(s.get("max_abs_delta") or 0) >= args.min_abs_delta
    ]
    actionable.sort(key=lambda s: float(s.get("max_abs_delta") or 0), reverse=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "write" if args.write else "audit",
        "target_districts": list(TARGET_DISTRICTS),
        "min_abs_delta": args.min_abs_delta,
        "files_scanned": len(summaries),
        "files_with_actionable_gaps": len(actionable),
        "districts_changed": sum(int(s.get("changed_districts") or 0) for s in summaries),
        "top_gaps": [
            {
                "file": s.get("file"),
                "max_abs_delta": s.get("max_abs_delta"),
                "changed_districts": s.get("changed_districts"),
            }
            for s in actionable[:40]
        ],
        "summaries": summaries,
    }

    out = args.summary_json if args.summary_json.is_absolute() else ROOT / args.summary_json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "mode": report["mode"],
                "files_scanned": report["files_scanned"],
                "files_with_actionable_gaps": report["files_with_actionable_gaps"],
                "districts_changed": report["districts_changed"],
                "summary_json": str(out),
                "top_gaps": report["top_gaps"][:15],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
