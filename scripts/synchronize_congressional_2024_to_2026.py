#!/usr/bin/env python3
"""Share exact 2026 congressional totals with unchanged 2024-line districts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
# The 2026 plan changes only CD1 and CD3; all other district lines can share
# the authoritative NCGA-calibrated totals.
UNCHANGED_DISTRICTS = {str(i) for i in range(2, 15) if i != 3}
VALUE_KEYS = ("dem_votes", "rep_votes", "other_votes", "total_votes", "margin", "margin_pct", "winner", "competitiveness")


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in VALUE_KEYS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data/district_contests_2026_lines")
    parser.add_argument("--target-dir", type=Path, default=ROOT / "data/district_contests_2024_lines")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    changes: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    changed_files: set[str] = set()
    for source_path in sorted(args.source_dir.glob("congressional_*.json")):
        source = json.loads(source_path.read_text(encoding="utf-8"))
        if not (source.get("meta") or {}).get("ncga_statpack_calibrated"):
            continue
        target_path = args.target_dir / source_path.name
        if not target_path.exists():
            skipped.append({"file": source_path.name, "reason": "target_missing"})
            continue
        target = json.loads(target_path.read_text(encoding="utf-8"))
        source_results = ((source.get("general") or {}).get("results") or {})
        target_results = ((target.get("general") or {}).get("results") or {})
        changed = False
        for district in sorted(UNCHANGED_DISTRICTS, key=int):
            if district not in source_results or district not in target_results:
                skipped.append({"file": source_path.name, "district": district, "reason": "district_missing"})
                continue
            before = snapshot(target_results[district])
            after = snapshot(source_results[district])
            if before == after:
                continue
            changes.append({"file": target_path.relative_to(ROOT).as_posix(), "district": district, "before": before, "after": after})
            if args.write:
                for key in VALUE_KEYS:
                    target_results[district][key] = source_results[district].get(key)
                changed = True
        if args.write and changed:
            meta = target.setdefault("meta", {})
            meta["ncga_shared_from_2026_for_unchanged_districts"] = True
            meta["ncga_shared_districts"] = sorted(UNCHANGED_DISTRICTS, key=int)
            meta["ncga_shared_source_file"] = source_path.relative_to(ROOT).as_posix()
            target_path.write_text(json.dumps(target, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            changed_files.add(target_path.relative_to(ROOT).as_posix())

    report = {
        "mode": "write" if args.write else "audit",
        "source_dir": str(args.source_dir),
        "target_dir": str(args.target_dir),
        "shared_districts": sorted(UNCHANGED_DISTRICTS, key=int),
        "changed_rows": len(changes),
        "changed_files": sorted(changed_files),
        "skipped": skipped,
        "changes": changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"mode": report["mode"], "changed_rows": len(changes), "changed_files": len(changed_files), "skipped": len(skipped)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
