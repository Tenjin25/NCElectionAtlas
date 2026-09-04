#!/usr/bin/env python3
"""Audit or apply calibrated NCSBE precinct-sort benchmarks to live district JSONs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from calibrate_district_slices_from_stats_csv import calculate_competitiveness  # noqa: E402
from build_ncsbe_congressional_precinct_sort_benchmarks import exact_ncga_district  # noqa: E402


FIELDS = ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct", "winner")


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=ROOT / "data/reports/ncsbe_all_plans_precinct_sort_benchmarks.json")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    args.benchmark = args.benchmark.resolve()
    args.report = args.report.resolve()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    changes: list[dict[str, Any]] = []
    preserved: list[dict[str, str]] = []
    skipped_missing_files: list[str] = []
    changed_files: set[str] = set()

    for year, year_payload in sorted(benchmark["years"].items()):
        for plan_name, plan in sorted(year_payload["plans"].items()):
            live_dir = ROOT / plan["live_dir"]
            scope = plan["scope"]
            for contest, districts in sorted(plan["results"].items()):
                path = live_dir / f"{scope}_{contest}.json"
                if not path.exists():
                    skipped_missing_files.append(path.relative_to(ROOT).as_posix())
                    continue
                raw_text = path.read_text(encoding="utf-8")
                payload = json.loads(raw_text)
                meta = payload.get("meta") or {}
                live = payload["general"]["results"]
                file_changed = False
                for district, values in districts.items():
                    if district not in live:
                        continue
                    if exact_ncga_district(meta, district):
                        preserved.append({"file": path.relative_to(ROOT).as_posix(), "district": district})
                        continue
                    before = snapshot(live[district])
                    after = snapshot(values)
                    if before == after:
                        continue
                    changes.append({
                        "year": int(year), "plan": plan_name, "scope": scope, "contest": contest,
                        "district": district, "file": path.relative_to(ROOT).as_posix(),
                        "winner_changed": before["winner"] != after["winner"], "before": before, "after": after,
                    })
                    if args.write:
                        live[district].update(after)
                        competition = live[district].setdefault("competitiveness", {})
                        competition["color"] = calculate_competitiveness(float(after["margin_pct"]))
                        file_changed = True
                if args.write and file_changed:
                    meta = payload.setdefault("meta", {})
                    meta["ncsbe_precinct_sort_calibrated"] = True
                    meta["ncsbe_precinct_sort_year"] = int(year)
                    meta["ncsbe_precinct_sort_plan"] = plan_name
                    meta["ncsbe_precinct_sort_method"] = benchmark["method"]
                    formatted = json.dumps(payload, indent=2, ensure_ascii=False) + "\n" if "\n" in raw_text.strip() else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
                    path.write_text(formatted, encoding="utf-8")
                    changed_files.add(path.relative_to(ROOT).as_posix())

    report = {
        "mode": "write" if args.write else "audit",
        "benchmark": args.benchmark.relative_to(ROOT).as_posix(),
        "changed_rows": len(changes), "winner_changes": sum(row["winner_changed"] for row in changes),
        "changed_files": sorted(changed_files), "preserved_exact_ncga_rows": len(preserved),
        "skipped_missing_files": sorted(set(skipped_missing_files)), "changes": changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "changed_rows", "winner_changes", "changed_files", "preserved_exact_ncga_rows")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
