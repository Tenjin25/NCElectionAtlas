#!/usr/bin/env python3
"""Audit or apply reconciled NCSBE 2024 statewide results to House JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from calibrate_district_slices_from_stats_csv import calculate_competitiveness


FIELDS = (
    "dem_votes",
    "rep_votes",
    "other_votes",
    "total_votes",
    "margin",
    "margin_pct",
    "winner",
    "competitiveness",
)


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in FIELDS}


def rebuilt(values: dict[str, Any]) -> dict[str, Any]:
    row = {key: values[key] for key in FIELDS if key != "competitiveness"}
    row["competitiveness"] = {"color": calculate_competitiveness(float(values["margin_pct"]))}
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--plan", choices=("2022_lines", "2024_lines"), required=True)
    parser.add_argument("--live-dir", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    contests = (benchmark.get("plans") or {}).get(args.plan) or {}
    changes: list[dict[str, Any]] = []
    missing: list[str] = []
    for contest, rows in sorted(contests.items()):
        path = args.live_dir / f"state_house_{contest}.json"
        if not path.exists():
            missing.append(str(path))
            continue
        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        live = ((payload.get("general") or {}).get("results") or {})
        file_changed = False
        for district, values in rows.items():
            current = live.get(district)
            if not isinstance(current, dict):
                missing.append(f"{path}:HD-{district}")
                continue
            before = snapshot(current)
            after = rebuilt(values)
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
                for key, value in after.items():
                    if key == "competitiveness" and isinstance(current.get(key), dict):
                        current[key]["color"] = value["color"]
                    else:
                        current[key] = value
                file_changed = True
        if args.write and file_changed:
            meta = payload.setdefault("meta", {})
            if isinstance(meta, dict):
                meta["ncsbe2024_reconciled_source"] = benchmark.get("source")
                meta["ncsbe2024_official_totals_source"] = benchmark.get("official_totals_source")
                meta["ncsbe2024_reconciled_method"] = benchmark.get("method")
                meta["ncsbe2024_plan"] = ((benchmark.get("audits") or {}).get(args.plan) or {}).get(
                    "plan_id"
                )
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
        "contests": sorted(contests),
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
