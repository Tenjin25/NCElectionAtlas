"""Materialize block-assignment CSVs and copy VAP for onemap aggregation retries."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def write_assign(src: Path, out: Path, block_col: str, district_col: str) -> None:
    df = pd.read_csv(src, dtype=str)
    out_df = pd.DataFrame(
        {
            block_col: df["block_geoid20"].astype(str).str.zfill(15),
            district_col: df["district"].astype(str).str.strip(),
        }
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out, index=False)
    print(f"Wrote {len(out_df):,} -> {out}")


def main() -> None:
    specs = [
        (
            ROOT / "data/tmp/block_assign_extract",
            [
                (
                    ROOT
                    / "NCPrecinctMap_reinit_2026-04-29/data/crosswalks/block20_to_2022_state_house.csv",
                    "SL 2022-4.csv",
                    "Block",
                    "District",
                ),
                (
                    ROOT
                    / "NCPrecinctMap_reinit_2026-04-29/data/crosswalks/block20_to_2022_state_senate.csv",
                    "SL 2022-2.csv",
                    "Block",
                    "District",
                ),
                (
                    ROOT / "NCPrecinctMap_reinit_2026-04-29/data/crosswalks/block20_to_cd118.csv",
                    "NC_CD118.csv",
                    "GEOID",
                    "CDFP",
                ),
            ],
        ),
        (
            ROOT / "data/tmp/block_assign_extract_2024",
            [
                (
                    ROOT / "data/crosswalks/block20_to_2024_state_house.csv",
                    "SL_2024_4.csv",
                    "Block",
                    "District",
                ),
                (
                    ROOT / "data/crosswalks/block20_to_2024_state_senate.csv",
                    "SL_2024_2.csv",
                    "Block",
                    "District",
                ),
                (
                    ROOT / "data/crosswalks/block20_to_cd119.csv",
                    "NC_CD119.csv",
                    "GEOID",
                    "CDFP",
                ),
            ],
        ),
        (
            ROOT / "data/tmp/block_assign_extract_2026",
            [
                (
                    ROOT / "data/crosswalks/block20_to_cd2026_sl2025_95.csv",
                    "NC_CD2026.csv",
                    "GEOID",
                    "CDFP",
                ),
            ],
        ),
    ]
    for out_dir, files in specs:
        for src, name, bcol, dcol in files:
            write_assign(src, out_dir / name, bcol, dcol)

    vap_src = ROOT / "NCPrecinctMap_reinit_2026-04-29/data/census/block_vap_2020_nc.csv"
    vap_dst = ROOT / "data/census/block_vap_2020_nc.csv"
    vap_dst.parent.mkdir(parents=True, exist_ok=True)
    if not vap_dst.exists():
        vap_dst.write_bytes(vap_src.read_bytes())
        print(f"Copied VAP -> {vap_dst}")
    else:
        print(f"VAP already present: {vap_dst}")


if __name__ == "__main__":
    main()
