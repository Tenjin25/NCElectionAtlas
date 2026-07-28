#!/usr/bin/env python3
"""Promote congressional slices approved by the historical audit."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "data/reports/urban_sf1_historical"
AUDIT = REPORT_DIR / "congressional_outlier_audit_2000_2004.json"
BACKUP = REPORT_DIR / "pre_promotion_congressional_2002_2004"
MANIFEST = REPORT_DIR / "promotion_congressional_2002_2004.json"
STAGING = {
    2022: ROOT / "data/district_contests_urban_sf1_2022_lines",
    2024: ROOT / "data/district_contests_urban_sf1_2024_lines",
}
PRODUCTION = {
    2022: ROOT / "data/district_contests",
    2024: ROOT / "data/district_contests_2024_lines",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vote_total(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        int(row["total_votes"])
        for row in payload["general"]["results"].values()
    )


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    approved = audit.get("promotion_files") or []
    if not approved:
        raise RuntimeError("Congressional audit approved no files.")
    BACKUP.mkdir(parents=True, exist_ok=True)
    records = []
    for item in approved:
        line_year = int(item["line_year"])
        filename = str(item["file"])
        source = STAGING[line_year] / filename
        target = PRODUCTION[line_year] / filename
        backup = BACKUP / str(line_year) / filename
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(target, backup)
        old_sha = digest(target)
        source_sha = digest(source)
        temporary = target.with_suffix(target.suffix + ".urban-sf1-tmp")
        shutil.copy2(source, temporary)
        temporary.replace(target)
        if digest(target) != source_sha:
            raise RuntimeError(f"Post-copy hash mismatch: {line_year} {filename}")
        records.append(
            {
                "line_year": line_year,
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
        "schema": "urban_sf1_congressional_promotion.v1",
        "production_modified": True,
        "held_2000_files": audit.get("held_2000_files") or [],
        "files": records,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
