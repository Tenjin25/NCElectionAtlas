#!/usr/bin/env python3
"""Download the official statewide 2024 NCSBE precinct-sort export."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


URL = (
    "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/"
    "results_precinct_sort/STATEWIDE_PRECINCT_SORT.txt"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("downloads/ncsbe/2024_precinct_sort/STATEWIDE_PRECINCT_SORT.txt"),
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    status = "existing"
    if args.force or not args.output.exists() or not args.output.stat().st_size:
        partial = args.output.with_suffix(args.output.suffix + ".part")
        request = urllib.request.Request(
            URL, headers={"User-Agent": "NCPrecinctMap NCSBE source fetcher/1.0"}
        )
        with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as out:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                out.write(chunk)
        partial.replace(args.output)
        status = "downloaded"

    payload = {
        "schema": "ncsbe2024_precinct_sort_source.v1",
        "election_date": "2024-11-05",
        "url": URL,
        "path": str(args.output),
        "bytes": args.output.stat().st_size,
        "sha256": sha256(args.output),
        "status": status,
    }
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
