#!/usr/bin/env python3
"""Audit or apply official NCSBE 2016 precinct-sort projections to House rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from calibrate_district_slices_from_stats_csv import calculate_competitiveness


def projected_row(values: dict[str, Any]) -> dict[str, Any]:
    dem = int(round(float(values["dem_votes_float"])))
    rep = int(round(float(values["rep_votes_float"])))
    other = int(round(float(values["other_votes_float"])))
    total = dem + rep + other
    margin = rep - dem
    margin_pct = round((margin / total) * 100.0, 2) if total else 0.0
    return {
        "dem_votes": dem,
        "rep_votes": rep,
        "other_votes": other,
        "total_votes": total,
        "margin": margin,
        "margin_pct": margin_pct,
        "winner": "REP" if margin > 0 else ("DEM" if margin < 0 else "TIE"),
        "competitiveness": {"color": calculate_competitiveness(margin_pct)},
    }


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "dem_votes",
            "rep_votes",
            "other_votes",
            "total_votes",
            "margin",
            "margin_pct",
            "winner",
            "competitiveness",
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--plan", choices=("2022_lines", "2024_lines"), required=True)
    parser.add_argument("--live-dir", type=Path, required=True)
    parser.add_argument("--contests", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    requested = {part.strip() for part in args.contests.split(",") if part.strip()}
    plan_contests = (benchmark.get("plans") or {}).get(args.plan) or {}
    changes: list[dict[str, Any]] = []
    missing: list[str] = []

    for contest in sorted(requested):
        rows = plan_contests.get(contest)
        if not isinstance(rows, dict):
            missing.append(f"benchmark:{contest}")
            continue
        path = args.live_dir / f"state_house_{contest}.json"
        if not path.exists():
            missing.append(str(path))
            continue
        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        results = ((payload.get("general") or {}).get("results") or {})
        file_changed = False
        for district, values in rows.items():
            row = results.get(district)
            if not isinstance(row, dict):
                missing.append(f"{path}:HD-{district}")
                continue
            before = snapshot(row)
            after = {**before, **projected_row(values)}
            if before == after:
                continue
            changes.append(
                {
                    "file": str(path),
                    "contest": contest,
                    "district": district,
                    "before": before,
                    "after": after,
                }
            )
            if args.write:
                for key, value in projected_row(values).items():
                    if key == "competitiveness" and isinstance(row.get(key), dict):
                        row[key]["color"] = value["color"]
                    else:
                        row[key] = value
                file_changed = True

        if args.write and file_changed:
            meta = payload.setdefault("meta", {})
            if isinstance(meta, dict):
                meta["targeted_ncsbe_precinct_sort_districts"] = benchmark.get(
                    "target_districts", []
                )
                meta["targeted_ncsbe_precinct_sort_source"] = benchmark.get("source")
                meta["targeted_ncsbe_precinct_sort_method"] = benchmark.get("method")
            was_pretty = "\n" in raw_text.strip() and len(raw_text.strip().splitlines()) > 1
            output = (
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
                if was_pretty
                else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            )
            path.write_text(output, encoding="utf-8")

    report = {
        "mode": "write" if args.write else "audit",
        "plan": args.plan,
        "source": benchmark.get("source"),
        "method": benchmark.get("method"),
        "contests": sorted(requested),
        "changed_rows": len(changes),
        "missing": missing,
        "changes": changes,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: report[key] for key in ("mode", "plan", "contests", "changed_rows", "missing")},
            indent=2,
        )
    )
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
