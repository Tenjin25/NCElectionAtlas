"""
Build 2020 Census demographic summaries for NC court-ordered 2022 districts
(congressional, state house, state senate) using area-weighted VTD crosswalks.

Outputs (overwrites existing):
  data/nc_congressional_districts.csv
  data/nc_state_house_districts.csv
  data/nc_state_senate_districts.csv

Columns written:
  district, total_population, white_vap_pct, black_vap_pct, hispanic_vap_pct

Usage:
  python scripts/build_district_demographics.py
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DEMO_ZIP = ROOT / "_external" / "vtd_data" / "2020_VTD" / "NC" / "Demographic_Data_NC.v06.zip"
DEMO_CSV_INSIDE = "demographic_data_NC.v06.csv"

CROSSWALK_CD    = ROOT / "data" / "crosswalks" / "vtd20_to_cd118.csv"
CROSSWALK_HOUSE = ROOT / "data" / "crosswalks" / "vtd20_to_2024_state_house.csv"
CROSSWALK_SEN   = ROOT / "data" / "crosswalks" / "vtd20_to_2024_state_senate.csv"

OUT_CD    = ROOT / "data" / "nc_congressional_districts.csv"
OUT_HOUSE = ROOT / "data" / "nc_state_house_districts.csv"
OUT_SEN   = ROOT / "data" / "nc_state_senate_districts.csv"

# 2020 Census total population and VAP columns in the demographic file
DEMO_COLS = {
    "GEOID20": str,
    "T_20_CENS_Total": float,   # total population
    "V_20_VAP_Total": float,    # VAP total
    "V_20_VAP_White": float,    # VAP White (non-Hispanic)
    "V_20_VAP_Black": float,    # VAP Black (alone or in combination)
    "V_20_VAP_Hispanic": float, # VAP Hispanic
}

# ---------------------------------------------------------------------------
# Load demographics
# ---------------------------------------------------------------------------
def load_demographics() -> pd.DataFrame:
    print(f"Reading demographics from {DEMO_ZIP.name} ...")
    with zipfile.ZipFile(DEMO_ZIP) as zf:
        with zf.open(DEMO_CSV_INSIDE) as f:
            demo = pd.read_csv(
                io.TextIOWrapper(f, encoding="utf-8"),
                usecols=list(DEMO_COLS.keys()),
                dtype={"GEOID20": str},
            )
    # Ensure numeric columns are float
    for col in list(DEMO_COLS.keys())[1:]:
        demo[col] = pd.to_numeric(demo[col], errors="coerce").fillna(0.0)
    print(f"  Loaded {len(demo):,} VTDs")
    return demo


# ---------------------------------------------------------------------------
# Load crosswalk
# ---------------------------------------------------------------------------
def load_crosswalk(path: Path) -> pd.DataFrame:
    cw = pd.read_csv(path, dtype={"vtd_geoid20": str, "district": str, "area_weight": float})
    return cw[["vtd_geoid20", "district", "area_weight"]].copy()


# ---------------------------------------------------------------------------
# Build demographics for one district type
# ---------------------------------------------------------------------------
def build_district_demographics(
    demo: pd.DataFrame,
    crosswalk_path: Path,
    out_path: Path,
    district_label: str,
) -> None:
    print(f"\nBuilding {district_label} demographics ...")
    cw = load_crosswalk(crosswalk_path)
    print(f"  Crosswalk rows: {len(cw):,}, unique districts: {cw['district'].nunique()}")

    # Join demographics onto crosswalk using the VTD GEOID
    merged = cw.merge(demo, left_on="vtd_geoid20", right_on="GEOID20", how="left")
    unmatched = merged["T_20_CENS_Total"].isna().sum()
    if unmatched > 0:
        print(f"  WARNING: {unmatched} crosswalk rows had no demographic match")

    # Weight each demographic value by the area weight for this VTD-district slice
    for col in ["T_20_CENS_Total", "V_20_VAP_Total", "V_20_VAP_White", "V_20_VAP_Black", "V_20_VAP_Hispanic"]:
        merged[col] = merged[col].fillna(0.0) * merged["area_weight"]

    # Aggregate to district level
    agg = (
        merged.groupby("district")[
            ["T_20_CENS_Total", "V_20_VAP_Total", "V_20_VAP_White", "V_20_VAP_Black", "V_20_VAP_Hispanic"]
        ]
        .sum()
        .reset_index()
    )
    agg = agg.sort_values("district")

    # Compute percentages (0–100, rounded to 1 decimal place)
    def pct(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
        safe_denom = denominator.replace(0, float("nan"))
        return (numerator / safe_denom * 100).round(1).fillna(0.0)

    agg["white_vap_pct"]    = pct(agg["V_20_VAP_White"],    agg["V_20_VAP_Total"])
    agg["black_vap_pct"]    = pct(agg["V_20_VAP_Black"],    agg["V_20_VAP_Total"])
    agg["hispanic_vap_pct"] = pct(agg["V_20_VAP_Hispanic"], agg["V_20_VAP_Total"])
    agg["total_population"] = agg["T_20_CENS_Total"].round(0).astype(int)

    # Read the existing CSV to preserve the district number format (e.g. "01" vs "1")
    existing = pd.read_csv(out_path, dtype={"district": str})
    existing_districts = existing["district"].tolist()

    # Build output rows, preserving the original district key format
    out_rows = []
    for orig_d in existing_districts:
        # Try exact match first, then zero-stripped / zero-padded variants
        row = agg[agg["district"] == orig_d]
        if row.empty:
            # Try matching by integer value
            try:
                int_d = int(orig_d)
                row = agg[agg["district"].apply(lambda x: int(x) == int_d)]
            except ValueError:
                pass
        if row.empty:
            print(f"  WARNING: district '{orig_d}' not found in crosswalk aggregation")
            out_rows.append({
                "district": orig_d,
                "total_population": 0,
                "white_vap_pct": 0.0,
                "black_vap_pct": 0.0,
                "hispanic_vap_pct": 0.0,
            })
        else:
            r = row.iloc[0]
            out_rows.append({
                "district": orig_d,
                "total_population": int(r["total_population"]),
                "white_vap_pct": float(r["white_vap_pct"]),
                "black_vap_pct": float(r["black_vap_pct"]),
                "hispanic_vap_pct": float(r["hispanic_vap_pct"]),
            })

    result = pd.DataFrame(out_rows, columns=["district", "total_population", "white_vap_pct", "black_vap_pct", "hispanic_vap_pct"])
    result.to_csv(out_path, index=False)
    print(f"  Written {len(result)} districts to {out_path.relative_to(ROOT)}")

    # Sanity check: print a few rows
    print(result.head(5).to_string(index=False))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    demo = load_demographics()

    build_district_demographics(demo, CROSSWALK_CD,    OUT_CD,    "Congressional (CD118)")
    build_district_demographics(demo, CROSSWALK_HOUSE, OUT_HOUSE, "State House (2024 lines)")
    build_district_demographics(demo, CROSSWALK_SEN,   OUT_SEN,   "State Senate (2024 lines)")

    print("\nDone.")


if __name__ == "__main__":
    main()
