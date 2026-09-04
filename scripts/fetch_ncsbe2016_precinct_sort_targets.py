#!/usr/bin/env python3
"""Download official 2016 precinct-sort files for the HD-108/109/110 counties."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


COUNTIES = ("CLEVELAND", "GASTON", "LINCOLN")
BASE_URL = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2016_11_08/results_precinct_sort"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("downloads/ncsbe/2016_precinct_sort"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for county in COUNTIES:
        name = f"{county}_PRECINCT_SORT.txt"
        url = f"{BASE_URL}/{name}"
        target = args.output_dir / name
        status = "existing"
        if args.force or not target.exists() or not target.stat().st_size:
            request = urllib.request.Request(
                url, headers={"User-Agent": "NCPrecinctMap NCSBE source fetcher/1.0"}
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                target.write_bytes(response.read())
            status = "downloaded"
        files.append(
            {
                "county": county,
                "url": url,
                "path": str(target),
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
                "status": status,
            }
        )

    manifest = {
        "schema": "ncsbe2016_precinct_sort_target_sources.v1",
        "election_date": "2016-11-08",
        "files": files,
    }
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
