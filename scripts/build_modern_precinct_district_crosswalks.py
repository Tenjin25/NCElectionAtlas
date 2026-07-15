"""Build block-weighted modern precinct -> district crosswalks.

The live atlas renders district carryover using precinct-level crosswalk CSVs.
This script derives those CSVs from the configured modern block->precinct map
(December 2025 by default) and block-level district assignments, so the overlay
chain follows the same modern target basis as precinct contest display.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class DistrictCrosswalkSpec:
    output_name: str
    assignment_path: Path
    block_col: str
    district_col: str
    district_type: str
    target_year: int
    plan_id: str
    plan_label: str
    district_width: int
    district_prefix: str
    district_name_template: str


DEFAULT_SPECS = [
    DistrictCrosswalkSpec(
        output_name="precinct_to_2022_state_house.csv",
        assignment_path=ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv",
        block_col="Block",
        district_col="District",
        district_type="state_house",
        target_year=2022,
        plan_id="nc_court_ordered_2022",
        plan_label="NC Court-Ordered 2022 Lines (block-weighted December 2025 precinct basis)",
        district_width=3,
        district_prefix="HD",
        district_name_template="State House District {number}",
    ),
    DistrictCrosswalkSpec(
        output_name="precinct_to_2022_state_senate.csv",
        assignment_path=ROOT / "data/tmp/block_assign_extract/SL 2022-2.csv",
        block_col="Block",
        district_col="District",
        district_type="state_senate",
        target_year=2022,
        plan_id="nc_court_ordered_2022",
        plan_label="NC Court-Ordered 2022 Lines (block-weighted December 2025 precinct basis)",
        district_width=2,
        district_prefix="SD",
        district_name_template="State Senate District {number}",
    ),
    DistrictCrosswalkSpec(
        output_name="precinct_to_cd118.csv",
        assignment_path=ROOT / "data/tmp/block_assign_extract/NC_CD118.csv",
        block_col="GEOID",
        district_col="CDFP",
        district_type="congressional",
        target_year=2022,
        plan_id="cd118",
        plan_label="Congressional Districts, 118th Congress (block-weighted December 2025 precinct basis)",
        district_width=2,
        district_prefix="CD",
        district_name_template="Congressional District {number}",
    ),
    DistrictCrosswalkSpec(
        output_name="precinct_to_2024_state_house.csv",
        assignment_path=ROOT / "data/tmp/block_assign_extract_2024/SL_2024_4.csv",
        block_col="Block",
        district_col="District",
        district_type="state_house",
        target_year=2024,
        plan_id="tiger_line_2024",
        plan_label="2024 State House Lines (block-weighted December 2025 precinct basis)",
        district_width=3,
        district_prefix="HD",
        district_name_template="State House District {number}",
    ),
    DistrictCrosswalkSpec(
        output_name="precinct_to_2024_state_senate.csv",
        assignment_path=ROOT / "data/tmp/block_assign_extract_2024/SL_2024_2.csv",
        block_col="Block",
        district_col="District",
        district_type="state_senate",
        target_year=2024,
        plan_id="tiger_line_2024",
        plan_label="2024 State Senate Lines (block-weighted December 2025 precinct basis)",
        district_width=2,
        district_prefix="SD",
        district_name_template="State Senate District {number}",
    ),
    DistrictCrosswalkSpec(
        output_name="precinct_to_cd119.csv",
        assignment_path=ROOT / "data/tmp/block_assign_extract_2024/NC_CD119.csv",
        block_col="GEOID",
        district_col="CDFP",
        district_type="congressional",
        target_year=2024,
        plan_id="cd119",
        plan_label="Congressional Districts, 119th Congress (block-weighted December 2025 precinct basis)",
        district_width=2,
        district_prefix="CD",
        district_name_template="Congressional District {number}",
    ),
    DistrictCrosswalkSpec(
        output_name="precinct_to_cd2026_sl2025_95.csv",
        assignment_path=ROOT / "data/tmp/block_assign_extract_2026/NC_CD2026.csv",
        block_col="GEOID",
        district_col="CDFP",
        district_type="congressional",
        target_year=2026,
        plan_id="sl2025_95",
        plan_label="SL 2025-95 Congressional Lines (block-weighted December 2025 precinct basis)",
        district_width=2,
        district_prefix="CD",
        district_name_template="Congressional District {number}",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--precinct-block-map",
        type=Path,
        default=ROOT / "data/crosswalks/block20_to_onemap_2025_12.csv",
        help="Modern block->precinct assignment map.",
    )
    parser.add_argument(
        "--vap-csv",
        type=Path,
        default=ROOT / "data/census/block_vap_2020_nc.csv",
        help="Optional VAP-by-block weights. Falls back to block counts for zero-VAP precincts.",
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data/crosswalks")
    return parser.parse_args()


def clean_block(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.zfill(15)


def clean_precinct(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.upper().str.replace(r"\s+", " ", regex=True)


def district_code(value: object, width: int) -> str:
    raw = str(value or "").strip()
    numeric = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
    if pd.notna(numeric):
        return f"{int(numeric):0{width}d}"
    return raw.upper()


def district_number(value: object) -> str:
    code = str(value or "").strip()
    numeric = pd.to_numeric(pd.Series([code]), errors="coerce").iloc[0]
    if pd.notna(numeric):
        return str(int(numeric))
    return code


def district_name(value: object, spec: DistrictCrosswalkSpec) -> str:
    code = district_code(value, spec.district_width)
    number = str(int(code)) if code.isdigit() else code
    return spec.district_name_template.format(number=number, code=code)


def load_precinct_blocks(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    required = {"block_geoid20", "precinct_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    out = df[["block_geoid20", "precinct_id"]].copy()
    out["block_geoid20"] = clean_block(out["block_geoid20"])
    out["precinct_key"] = clean_precinct(out["precinct_id"])
    out = out[(out["block_geoid20"] != "") & (out["precinct_key"] != "")]
    return out[["block_geoid20", "precinct_key"]].drop_duplicates("block_geoid20")


def load_vap(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["block_geoid20", "vap_count"])
    df = pd.read_csv(path, dtype=str)
    geoid_col = "block_geoid20" if "block_geoid20" in df.columns else "GEOID20"
    vap_col = "vap_count" if "vap_count" in df.columns else "vap20"
    if geoid_col not in df.columns or vap_col not in df.columns:
        raise ValueError(f"{path} must include a block GEOID and VAP column")
    out = df[[geoid_col, vap_col]].copy()
    out.columns = ["block_geoid20", "vap_count"]
    out["block_geoid20"] = clean_block(out["block_geoid20"])
    out["vap_count"] = pd.to_numeric(out["vap_count"], errors="coerce").fillna(0.0)
    return out.drop_duplicates("block_geoid20")


def load_assignment(spec: DistrictCrosswalkSpec) -> pd.DataFrame:
    df = pd.read_csv(spec.assignment_path, dtype=str)
    missing = {spec.block_col, spec.district_col} - set(df.columns)
    if missing:
        raise ValueError(f"{spec.assignment_path} missing columns: {sorted(missing)}")
    out = df[[spec.block_col, spec.district_col]].copy()
    out.columns = ["block_geoid20", "district"]
    out["block_geoid20"] = clean_block(out["block_geoid20"])
    out["district"] = out["district"].fillna("").astype(str).str.strip()
    out = out[(out["block_geoid20"] != "") & (out["district"] != "")]
    return out.drop_duplicates("block_geoid20")


def build_crosswalk(
    spec: DistrictCrosswalkSpec,
    precinct_blocks: pd.DataFrame,
    vap: pd.DataFrame,
    out_dir: Path,
) -> dict[str, object]:
    assignment = load_assignment(spec)
    joined = precinct_blocks.merge(assignment, on="block_geoid20", how="inner").merge(vap, on="block_geoid20", how="left")
    joined["vap_count"] = joined["vap_count"].fillna(0.0)

    grouped = (
        joined.groupby(["precinct_key", "district"], as_index=False)
        .agg(block_count=("block_geoid20", "nunique"), vap_count=("vap_count", "sum"))
    )
    totals = (
        joined.groupby("precinct_key", as_index=False)
        .agg(precinct_block_total=("block_geoid20", "nunique"), precinct_vap_total=("vap_count", "sum"))
    )
    grouped = grouped.merge(totals, on="precinct_key", how="left")
    grouped["weight_source"] = "vap"
    grouped["weight"] = grouped["vap_count"]
    zero_vap = grouped["precinct_vap_total"] <= 0
    grouped.loc[zero_vap, "weight_source"] = "block_count"
    grouped.loc[zero_vap, "weight"] = grouped.loc[zero_vap, "block_count"].astype(float)
    denom = grouped.groupby("precinct_key")["weight"].transform("sum").replace(0, pd.NA)
    grouped["area_weight"] = grouped["weight"] / denom
    grouped = grouped[grouped["area_weight"].fillna(0) > 0].copy()

    grouped["district_num"] = grouped["district"].map(district_number)
    grouped["district_code"] = grouped["district"].map(lambda value: district_code(value, spec.district_width))
    grouped["district_label"] = grouped["district_code"].map(lambda code: f"{spec.district_prefix}-{code}")
    grouped["district_geoid"] = grouped["district_code"].map(lambda code: f"37{code}" if code else "")
    grouped["district_name"] = grouped["district"].map(lambda value: district_name(value, spec))
    grouped["district_type"] = spec.district_type
    grouped["target_year"] = spec.target_year
    grouped["plan_id"] = spec.plan_id
    grouped["plan_label"] = spec.plan_label
    grouped["intersect_area_m2"] = ""
    grouped["precinct_area_m2"] = ""

    columns = [
        "precinct_key",
        "district",
        "district_geoid",
        "district_name",
        "intersect_area_m2",
        "precinct_area_m2",
        "area_weight",
        "district_num",
        "district_code",
        "district_label",
        "district_type",
        "target_year",
        "plan_id",
        "plan_label",
        "block_count",
        "precinct_block_total",
        "vap_count",
        "precinct_vap_total",
        "weight_source",
    ]
    out = grouped[columns].sort_values(["precinct_key", "area_weight", "district_code"], ascending=[True, False, True])
    out_path = out_dir / spec.output_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)

    weight_sums = out.groupby("precinct_key")["area_weight"].sum()
    summary = {
        "output": str(out_path.relative_to(ROOT)),
        "rows": int(len(out)),
        "precincts": int(out["precinct_key"].nunique()),
        "source_precincts": int(precinct_blocks["precinct_key"].nunique()),
        "joined_blocks": int(joined["block_geoid20"].nunique()),
        "assignment_blocks": int(assignment["block_geoid20"].nunique()),
        "coverage_pct": round(float(out["precinct_key"].nunique() / precinct_blocks["precinct_key"].nunique() * 100), 6),
        "weight_sum_min": round(float(weight_sums.min()), 12),
        "weight_sum_max": round(float(weight_sums.max()), 12),
        "zero_vap_precincts": int((totals["precinct_vap_total"] <= 0).sum()),
    }
    return summary


def main() -> None:
    args = parse_args()
    precinct_blocks = load_precinct_blocks(args.precinct_block_map)
    vap = load_vap(args.vap_csv)
    for spec in DEFAULT_SPECS:
        if not spec.assignment_path.exists():
            print(f"Skipping missing assignment: {spec.assignment_path}")
            continue
        summary = build_crosswalk(spec, precinct_blocks, vap, args.out_dir)
        print(
            f"{summary['output']}: rows={summary['rows']:,}; "
            f"precinct coverage={summary['coverage_pct']:.6f}%; "
            f"weight sum min/max={summary['weight_sum_min']:.6f}/{summary['weight_sum_max']:.6f}"
        )


if __name__ == "__main__":
    main()
