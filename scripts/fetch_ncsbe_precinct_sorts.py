#!/usr/bin/env python3
"""Download official NCSBE general-election precinct-sort exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


DATES = {2016: "2016_11_08", 2018: "2018_11_06", 2020: "2020_11_03", 2022: "2022_11_08", 2024: "2024_11_05"}
BUCKET = "https://s3.amazonaws.com/dl.ncsbe.gov"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def request(url: str, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(url, method=method, headers={"User-Agent": "NCPrecinctMap NCSBE source fetcher/1.0"})


def exists(url: str) -> bool:
    try:
        with urllib.request.urlopen(request(url, "HEAD"), timeout=60) as response:
            return response.status == 200
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


def list_keys(prefix: str) -> list[str]:
    url = f"{BUCKET}?list-type=2&prefix={urllib.parse.quote(prefix, safe='/')}"
    with urllib.request.urlopen(request(url), timeout=120) as response:
        root = ET.fromstring(response.read())
    namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    return [node.text or "" for node in root.findall("s3:Contents/s3:Key", namespace) if (node.text or "").lower().endswith(".txt")]


def download(url: str, path: Path) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    status = "existing"
    if not path.exists() or not path.stat().st_size:
        partial = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(request(url), timeout=300) as response, partial.open("wb") as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                output.write(chunk)
        partial.replace(path)
        status = "downloaded"
    return {"url": url, "path": path.as_posix(), "bytes": path.stat().st_size, "sha256": digest(path), "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=[2016, 2018, 2020, 2022, 2024])
    parser.add_argument("--output-root", type=Path, default=Path("downloads/ncsbe"))
    parser.add_argument("--manifest", type=Path, default=Path("data/reports/ncsbe_precinct_sort_sources.json"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    payload: dict[str, object] = {"schema": "ncsbe_precinct_sort_sources.v1", "years": {}}
    for year in args.years:
        date = DATES[year]
        prefix = f"ENRS/{date}/results_precinct_sort/"
        statewide_key = prefix + "STATEWIDE_PRECINCT_SORT.txt"
        statewide_url = f"{BUCKET}/{statewide_key}"
        keys = [statewide_key] if exists(statewide_url) else list_keys(prefix)
        destinations = [(f"{BUCKET}/{key}", args.output_root / f"{year}_precinct_sort" / Path(key).name) for key in keys]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            files = list(pool.map(lambda pair: download(*pair), destinations))
        payload["years"][str(year)] = {"election_date": date.replace("_", "-"), "files": files, "total_bytes": sum(int(item["bytes"]) for item in files)}
        print(json.dumps({"year": year, "files": len(files), "bytes": payload["years"][str(year)]["total_bytes"]}))
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
