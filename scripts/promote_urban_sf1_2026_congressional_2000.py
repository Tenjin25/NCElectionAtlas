#!/usr/bin/env python3
"""Promote validated 2000 contests onto the 2026 congressional plan."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "data/reports/urban_sf1_historical/full_ballot_2000_audit.json"
STAGING = ROOT / "data/district_contests_urban_sf1_2026_lines"
TARGET = ROOT / "data/district_contests_2026_lines"
BACKUP = (
    ROOT
    / "data/reports/urban_sf1_historical/pre_promotion_2026_congressional_2000"
)
MANIFEST = (
    ROOT
    / "data/reports/urban_sf1_historical/promotion_2026_congressional_2000.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def statewide_votes(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        int(row.get("total_votes") or 0)
        for row in payload["general"]["results"].values()
    )


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if not audit.get("geographic_sanity_passed"):
        raise RuntimeError("Full-ballot geographic sanity checks did not pass")

    candidates = sorted(
        (
            row
            for row in audit["file_summaries"]
            if row["line_year"] == 2026
            and row["scope"] == "congressional"
            and row["disposition"] == "promotion_candidate"
        ),
        key=lambda row: row["file"],
    )
    if len(candidates) != 18:
        raise RuntimeError(
            f"Expected 18 audited 2026 congressional candidates; found {len(candidates)}"
        )

    promoted = []
    TARGET.mkdir(parents=True, exist_ok=True)
    for row in candidates:
        source = STAGING / row["file"]
        target = TARGET / row["file"]
        backup = BACKUP / row["file"]

        old_sha = None
        old_votes = None
        if target.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            old_sha = sha256(target)
            old_votes = statewide_votes(target)

        shutil.copy2(source, target)
        promoted.append(
            {
                "line_year": 2026,
                "scope": "congressional",
                "file": row["file"],
                "contest_type": row["contest_type"],
                "old_production_sha256": old_sha,
                "new_production_sha256": sha256(target),
                "old_production_votes": old_votes,
                "new_production_votes": statewide_votes(target),
                "backup": rel(backup) if old_sha else None,
                "source": rel(source),
                "target": rel(target),
            }
        )

    payload = {
        "schema": "urban_sf1_2026_congressional_2000_promotion.v1",
        "production_modified": True,
        "geographic_sanity_checks": [
            row
            for row in audit["geographic_sanity_checks"]
            if row["line_year"] == 2026
        ],
        "files": promoted,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Promoted {len(promoted)} files; wrote {rel(MANIFEST)}")


if __name__ == "__main__":
    main()
