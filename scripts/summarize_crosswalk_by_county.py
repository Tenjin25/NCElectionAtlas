"""
Summarize district crosswalks by county for QC.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def summarize_crosswalk(path: Path, kind: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(path, dtype=str)
    df["area_weight"] = pd.to_numeric(df["area_weight"], errors="coerce").fillna(0.0)
    df["county"] = df["precinct_key"].str.split(" - ").str[0]

    # One row per county with district diversity and split counts.
    county_rows = []
    for county, g in df.groupby("county"):
        precinct_count = g["precinct_key"].nunique()
        all_districts = g["district_label"].nunique()
        main_districts = g.loc[g["area_weight"] >= 0.5, "district_label"].nunique()
        meaningful_districts = g.loc[g["area_weight"] >= 0.1, "district_label"].nunique()
        split_precincts = (g.groupby("precinct_key")["district_label"].nunique() > 1).sum()
        county_rows.append(
            {
                "crosswalk_type": kind,
                "county": county,
                "precincts": int(precinct_count),
                "districts_all_weights": int(all_districts),
                "districts_weight_ge_0_10": int(meaningful_districts),
                "districts_weight_ge_0_50": int(main_districts),
                "split_precincts": int(split_precincts),
                "split_precinct_pct": round((split_precincts / precinct_count * 100.0), 2)
                if precinct_count
                else 0.0,
            }
        )

    # Split-precinct detail rows.
    split = (
        df.groupby(["county", "precinct_key"])
        .agg(
            district_count=("district_label", "nunique"),
            district_list=("district_label", lambda s: ", ".join(sorted(set(s)))),
            max_weight=("area_weight", "max"),
        )
        .reset_index()
    )
    split = split[split["district_count"] > 1].copy()
    split.insert(0, "crosswalk_type", kind)
    split = split.sort_values(["county", "district_count", "precinct_key"], ascending=[True, False, True])

    county_summary = pd.DataFrame(county_rows).sort_values("county")
    return county_summary, split


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    crosswalk_dir = root / "data" / "crosswalks"
    report_dir = root / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    specs = [
        ("state_house", crosswalk_dir / "precinct_to_2022_state_house.csv"),
        ("state_senate", crosswalk_dir / "precinct_to_2022_state_senate.csv"),
        ("cd118", crosswalk_dir / "precinct_to_cd118.csv"),
    ]

    summaries = []
    splits = []
    for kind, path in specs:
        if not path.exists():
            print(f"Skipping missing file: {path}")
            continue
        s, sp = summarize_crosswalk(path, kind)
        summaries.append(s)
        splits.append(sp)

    if summaries:
        all_summary = pd.concat(summaries, ignore_index=True)
        out_summary = report_dir / "crosswalk_county_summary.csv"
        all_summary.to_csv(out_summary, index=False)
        print(f"Wrote {out_summary}")

    if splits:
        all_splits = pd.concat(splits, ignore_index=True)
        out_splits = report_dir / "crosswalk_split_precincts.csv"
        all_splits.to_csv(out_splits, index=False)
        print(f"Wrote {out_splits}")


if __name__ == "__main__":
    main()
