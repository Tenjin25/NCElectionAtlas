"""
Regression checker for precinct override suggestion tiers/canonical choices.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate gold precinct override cases against generated suggestions.")
    ap.add_argument(
        "--gold",
        type=Path,
        default=Path("data/reports/precinct_override_gold_cases_2020.csv"),
    )
    ap.add_argument(
        "--suggestions",
        type=Path,
        default=Path("data/reports/precinct_key_overrides_2020_suggestions.csv"),
    )
    ap.add_argument(
        "--overrides",
        type=Path,
        default=Path("data/mappings/precinct_key_overrides.csv"),
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    gold_path = args.gold if args.gold.is_absolute() else root / args.gold
    sugg_path = args.suggestions if args.suggestions.is_absolute() else root / args.suggestions
    ov_path = args.overrides if args.overrides.is_absolute() else root / args.overrides

    with open(sugg_path, "r", encoding="utf-8", newline="") as f:
        suggestions = {(r["year"].strip(), r["raw_precinct_key"].strip().upper()): r for r in csv.DictReader(f)}
    with open(ov_path, "r", encoding="utf-8", newline="") as f:
        overrides = {(r["year"].strip(), r["raw_precinct_key"].strip().upper()): r for r in csv.DictReader(f)}

    failures: list[str] = []
    checked = 0
    with open(gold_path, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            checked += 1
            key = (r["year"].strip(), r["raw_precinct_key"].strip().upper())
            hit = suggestions.get(key)
            ov_hit = overrides.get(key)
            exp_canon = r["expected_canonical_precinct_key"].strip().upper()
            exp_tier = r["expected_tier"].strip().upper()
            if ov_hit:
                got_ov_canon = ov_hit["canonical_precinct_key"].strip().upper()
                if got_ov_canon != exp_canon:
                    failures.append(f"{key[0]} {key[1]} override mismatch: expected {exp_canon}, got {got_ov_canon}")
                continue
            if not hit:
                failures.append(f"Missing suggestion for {key[0]} {key[1]}")
                continue
            got_canon = hit["suggested_canonical_precinct_key"].strip().upper()
            got_tier = (hit.get("tier") or hit.get("confidence") or "").strip().upper()
            if got_canon != exp_canon:
                failures.append(f"{key[0]} {key[1]} canonical mismatch: expected {exp_canon}, got {got_canon}")
            if got_tier != exp_tier:
                failures.append(f"{key[0]} {key[1]} tier mismatch: expected {exp_tier}, got {got_tier}")

    if failures:
        print(f"FAILED: {len(failures)} issues across {checked} gold cases")
        for m in failures:
            print(f"- {m}")
        sys.exit(1)

    print(f"PASS: {checked} gold cases validated")


if __name__ == "__main__":
    main()
