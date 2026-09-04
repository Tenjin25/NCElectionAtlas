#!/usr/bin/env python3
"""Audit or apply calibrated NCSBE 2024 results to congressional JSONs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from calibrate_district_slices_from_stats_csv import calculate_competitiveness  # noqa: E402


FIELDS = ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct", "winner", "competitiveness")


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in FIELDS}


def rebuilt(values: dict[str, Any]) -> dict[str, Any]:
    row = {key: values[key] for key in FIELDS if key != "competitiveness"}
    row["competitiveness"] = {"color": calculate_competitiveness(float(values["margin_pct"]))}
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--live-dir", type=Path, default=ROOT / "data/district_contests")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    changes: list[dict[str, Any]] = []
    changed_files: list[str] = []
    missing: list[str] = []
    for contest, rows in sorted((benchmark.get("results") or {}).items()):
        path = args.live_dir / f"congressional_{contest}.json"
        if not path.exists():
            missing.append(path.relative_to(ROOT).as_posix())
            continue
        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        live = ((payload.get("general") or {}).get("results") or {})
        file_changed = False
        for district, values in rows.items():
            current = live.get(district)
            if not isinstance(current, dict):
                missing.append(f"{path.relative_to(ROOT).as_posix()}:CD-{district}")
                continue
            before = snapshot(current)
            after = rebuilt(values)
            if before == after:
                continue
            changes.append({"file": path.relative_to(ROOT).as_posix(), "contest": contest, "district": district, "before": before, "after": after})
            if args.write:
                for key, value in after.items():
                    if key == "competitiveness" and isinstance(current.get(key), dict):
                        current[key]["color"] = value["color"]
                    else:
                        current[key] = value
                file_changed = True
        if args.write and file_changed:
            meta = payload.setdefault("meta", {})
            meta["ncsbe2024_precinct_sort_calibrated"] = True
            meta["ncsbe2024_precinct_sort_source"] = benchmark.get("source")
            meta["ncsbe2024_official_totals_source"] = benchmark.get("official_totals_source")
            meta["ncsbe2024_precinct_sort_method"] = benchmark.get("method")
            meta["ncsbe2024_precinct_sort_plan"] = benchmark.get("plan")
            output = json.dumps(payload, indent=2, ensure_ascii=False) + "\n" if "\n" in raw_text.strip() else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            path.write_text(output, encoding="utf-8")
            changed_files.append(path.relative_to(ROOT).as_posix())

    report = {
        "mode": "write" if args.write else "audit",
        "benchmark": args.benchmark.relative_to(ROOT).as_posix(),
        "live_dir": args.live_dir.relative_to(ROOT).as_posix(),
        "changed_rows": len(changes),
        "changed_files": changed_files,
        "missing": missing,
        "changes": changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "changed_rows", "changed_files", "missing")}, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
