"""
Extract 2020 block Voting Age Population (18+) from an NHGIS PL94-171 block extract.

Input (NHGIS ds248 2020 block for NC):
  - GEOCODE: 15-digit Census block GEOID (STATE(2)+COUNTY(3)+TRACT(6)+BLOCK(4))
  - U7D001: Total population 18 years and over (VAP)

Output:
  - CSV with columns: block_geoid20,vap
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--input",
        required=True,
        help="Path to NHGIS 2020 block CSV (e.g. nhgis0004_ds248_2020_block.csv).",
    )
    p.add_argument(
        "--output",
        required=True,
        help="Path to write extracted CSV (block_geoid20,vap).",
    )
    p.add_argument(
        "--state-fips",
        default="37",
        help="2-digit state FIPS to keep (default: 37 for NC).",
    )
    p.add_argument(
        "--chunksize",
        type=int,
        default=250_000,
        help="Rows per chunk when streaming input (default: 250000).",
    )
    return p.parse_args()


def iter_rows(input_path: Path, chunksize: int):
    """
    Stream CSV rows using pandas if available (fast), else fallback to csv.DictReader.
    Yields tuples (geocode, vap_int).
    """
    try:
        import pandas as pd  # type: ignore
    except Exception:
        pd = None

    if pd is None:
        with input_path.open("r", newline="", encoding="utf-8", errors="ignore") as f:
            r = csv.DictReader(f)
            for row in r:
                geocode = (row.get("GEOCODE") or "").strip()
                vap_raw = (row.get("U7D001") or "").strip()
                if not geocode:
                    continue
                try:
                    vap = int(vap_raw) if vap_raw != "" else 0
                except ValueError:
                    vap = 0
                yield geocode, vap
        return

    usecols = ["GEOCODE", "U7D001"]
    # dtype=str keeps leading zeros safe; we'll int-cast U7D001 manually.
    for chunk in pd.read_csv(
        input_path,
        usecols=usecols,
        dtype={"GEOCODE": "string", "U7D001": "string"},
        chunksize=chunksize,
        low_memory=True,
    ):
        # Ensure plain python strings + ints
        geocodes = chunk["GEOCODE"].astype("string").fillna("")
        vaps = chunk["U7D001"].astype("string").fillna("0")
        for geocode, vap_raw in zip(geocodes.tolist(), vaps.tolist()):
            geocode = (geocode or "").strip()
            if not geocode:
                continue
            try:
                vap = int(vap_raw) if vap_raw != "" else 0
            except ValueError:
                vap = 0
            yield geocode, vap


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    state_fips = str(args.state_fips).zfill(2)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_in = 0
    n_out = 0
    total_vap = 0

    with output_path.open("w", newline="", encoding="utf-8") as out_f:
        w = csv.writer(out_f)
        w.writerow(["block_geoid20", "vap"])

        for geocode, vap in iter_rows(input_path, args.chunksize):
            n_in += 1
            if not geocode.startswith(state_fips):
                continue
            # NC block GEOID20 is the 15-digit GEOCODE.
            block_geoid20 = geocode
            w.writerow([block_geoid20, vap])
            n_out += 1
            total_vap += vap

    print(f"Read rows: {n_in}")
    print(f"Wrote rows: {n_out}")
    print(f"Total VAP (18+): {total_vap}")
    print(f"Output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

