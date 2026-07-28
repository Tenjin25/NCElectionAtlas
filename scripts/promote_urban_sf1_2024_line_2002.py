#!/usr/bin/env python3
"""Promote the validated 2024-line 2002 legislative staging slices."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/district_contests_urban_sf1_2024_lines"
TARGET = ROOT / "data/district_contests_2024_lines"
BACKUP = (
    ROOT
    / "data/reports/urban_sf1_historical/pre_promotion_2024_line_2002"
)
FILES = (
    "state_house_us_senate_2002.json",
    "state_senate_us_senate_2002.json",
)
MANIFEST = (
    ROOT
    / "data/reports/urban_sf1_historical/promotion_2024_line_2002.json"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vote_total(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = payload["general"]["results"]
    return sum(int(row["total_votes"]) for row in results.values())


def main() -> None:
    BACKUP.mkdir(parents=True, exist_ok=True)
    for audit_name in (
        "district_outlier_audit_2002_2004.csv",
        "district_outlier_audit_2002_2004.json",
    ):
        audit_source = ROOT / "data/reports/urban_sf1_historical" / audit_name
        audit_backup = BACKUP / audit_name
        if audit_source.exists() and not audit_backup.exists():
            shutil.copy2(audit_source, audit_backup)
    records = []
    for filename in FILES:
        source = SOURCE / filename
        target = TARGET / filename
        backup = BACKUP / filename
        if not backup.exists():
            shutil.copy2(target, backup)
        old_sha = digest(target)
        source_sha = digest(source)
        temporary = target.with_suffix(target.suffix + ".urban-sf1-tmp")
        shutil.copy2(source, temporary)
        temporary.replace(target)
        if digest(target) != source_sha:
            raise RuntimeError(f"Post-copy hash mismatch: {filename}")
        records.append(
            {
                "file": filename,
                "old_production_sha256": old_sha,
                "new_production_sha256": source_sha,
                "old_production_votes": vote_total(backup),
                "new_production_votes": vote_total(target),
                "backup": str(backup.relative_to(ROOT)).replace("\\", "/"),
                "source": str(source.relative_to(ROOT)).replace("\\", "/"),
                "target": str(target.relative_to(ROOT)).replace("\\", "/"),
            }
        )
    payload = {
        "schema": "urban_sf1_2024_line_2002_promotion.v1",
        "production_modified": True,
        "files": records,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
