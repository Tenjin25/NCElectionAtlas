#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_districts(raw: str) -> list[str]:
    out: list[str] = []
    for token in (raw or "").split(","):
        t = token.strip()
        if not t:
            continue
        if t.upper().startswith("HD-"):
            t = t[3:].strip()
        # normalize to no leading zeros, numeric string
        n = int(t)
        out.append(str(n))
    # preserve order but de-dupe
    seen: set[str] = set()
    deduped: list[str] = []
    for d in out:
        if d in seen:
            continue
        seen.add(d)
        deduped.append(d)
    return deduped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy selected NC State House district results from 2022-lines contest slices into 2024-lines slices."
    )
    parser.add_argument(
        "--districts",
        required=True,
        help='Comma-separated district list, e.g. "HD-05,22,25,24,12"',
    )
    parser.add_argument(
        "--source-dir",
        default="data/district_contests",
        help="Directory containing 2022-lines contest slice JSONs.",
    )
    parser.add_argument(
        "--dest-dir",
        default="data/district_contests_2024_lines",
        help="Directory containing 2024-lines contest slice JSONs.",
    )
    args = parser.parse_args()

    districts = parse_districts(args.districts)
    if not districts:
        raise SystemExit("No districts parsed from --districts")

    root = Path(__file__).resolve().parent.parent
    source_dir = (root / args.source_dir).resolve()
    dest_dir = (root / args.dest_dir).resolve()

    if not source_dir.exists():
        raise SystemExit(f"Missing source dir: {source_dir}")
    if not dest_dir.exists():
        raise SystemExit(f"Missing dest dir: {dest_dir}")

    files_touched = 0
    entries_updated = 0

    for dest_path in sorted(dest_dir.glob("*.json")):
        if dest_path.name == "manifest.json":
            continue
        # Only State House slices (HD-xx). Avoid touching congressional/senate files.
        if not dest_path.name.startswith("state_house_"):
            continue

        source_path = source_dir / dest_path.name
        if not source_path.exists():
            continue

        try:
            src = json.loads(source_path.read_text(encoding="utf-8"))
            dst = json.loads(dest_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise SystemExit(f"Failed to parse JSON: {dest_path.name}: {e}") from e

        src_results = (((src.get("general") or {}).get("results")) or {})
        dst_general = (dst.get("general") or {})
        dst_results = (dst_general.get("results")) or {}

        if not isinstance(src_results, dict) or not isinstance(dst_results, dict):
            continue

        changed = False
        for d in districts:
            if d not in src_results:
                continue
            if dst_results.get(d) == src_results.get(d):
                continue
            dst_results[d] = src_results[d]
            entries_updated += 1
            changed = True

        if changed:
            dst_general["results"] = dst_results
            dst["general"] = dst_general
            dest_path.write_text(json.dumps(dst, indent=2), encoding="utf-8")
            files_touched += 1

    print(
        f"Updated {entries_updated} district result entries across {files_touched} files in {dest_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
