"""Report how SBE 2006 precincts bridge onto modern district block assignments.

This is a diagnostic/reusable artifact for early-era contests: it joins the
filled NHGIS-backed SBE 2006 block bridge to the modern block->district maps
used by district aggregation, then reports dominant districts and split shares
per SBE 2006 precinct.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class DistrictSpec:
    scope: str
    target_year: int
    district_type: str
    plan_id: str
    assignment_path: Path
    block_col: str
    district_col: str
    geometry_path: Path | None = None
    district_width: int = 2
    district_prefix: str = "CD"
    district_name_template: str = "{prefix}-{code}"


DEFAULT_SPECS = [
    DistrictSpec(
        scope="2022_state_house_mqp",
        target_year=2022,
        district_type="state_house",
        plan_id="sl_2022_mqp",
        assignment_path=ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv",
        block_col="Block",
        district_col="District",
        geometry_path=ROOT / "data/tileset/nc_state_house_2022_lines_tileset.geojson",
        district_width=3,
        district_prefix="HD",
        district_name_template="State House District {number}",
    ),
    DistrictSpec(
        scope="2022_state_senate_mqp",
        target_year=2022,
        district_type="state_senate",
        plan_id="sl_2022_mqp",
        assignment_path=ROOT / "data/tmp/block_assign_extract/SL 2022-2.csv",
        block_col="Block",
        district_col="District",
        geometry_path=ROOT / "data/tileset/nc_state_senate_2022_lines_tileset.geojson",
        district_width=2,
        district_prefix="SD",
        district_name_template="State Senate District {number}",
    ),
    DistrictSpec(
        scope="2022_congressional_cd118",
        target_year=2022,
        district_type="congressional",
        plan_id="cd118",
        assignment_path=ROOT / "data/tmp/block_assign_extract/NC_CD118.csv",
        block_col="GEOID",
        district_col="CDFP",
        geometry_path=ROOT / "data/tileset/nc_cd118_tileset.geojson",
        district_width=2,
        district_prefix="CD",
        district_name_template="Congressional District {number}",
    ),
    DistrictSpec(
        scope="2024_state_house",
        target_year=2024,
        district_type="state_house",
        plan_id="tiger_line_2024",
        assignment_path=ROOT / "data/crosswalks/block20_to_2024_state_house.csv",
        block_col="block_geoid20",
        district_col="district",
        geometry_path=ROOT / "data/tileset/nc_state_house_2024_lines_tileset.geojson",
        district_width=3,
        district_prefix="HD",
        district_name_template="State House District {number}",
    ),
    DistrictSpec(
        scope="2024_state_senate",
        target_year=2024,
        district_type="state_senate",
        plan_id="tiger_line_2024",
        assignment_path=ROOT / "data/crosswalks/block20_to_2024_state_senate.csv",
        block_col="block_geoid20",
        district_col="district",
        geometry_path=ROOT / "data/tileset/nc_state_senate_2024_lines_tileset.geojson",
        district_width=2,
        district_prefix="SD",
        district_name_template="State Senate District {number}",
    ),
    DistrictSpec(
        scope="2024_congressional_cd119",
        target_year=2024,
        district_type="congressional",
        plan_id="tiger_line_2024",
        assignment_path=ROOT / "data/crosswalks/block20_to_cd119.csv",
        block_col="block_geoid20",
        district_col="district",
        geometry_path=ROOT / "data/tileset/nc_cd119_tileset.geojson",
        district_width=2,
        district_prefix="CD",
        district_name_template="Congressional District {number}",
    ),
    DistrictSpec(
        scope="2026_congressional_sl2025_95",
        target_year=2026,
        district_type="congressional",
        plan_id="sl2025_95",
        assignment_path=ROOT / "data/tmp/block_assign_extract_2026/NC_CD2026.csv",
        block_col="GEOID",
        district_col="CDFP",
        geometry_path=ROOT / "data/tileset/nc_cd2026_sl2025_95_tileset.geojson",
        district_width=2,
        district_prefix="CD",
        district_name_template="Congressional District {number}",
    ),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sbe2006-block-map",
        type=Path,
        default=ROOT / "data/crosswalks/block20_to_sbe_2006_via_block00_nhgis_filled.csv",
    )
    p.add_argument("--vap-csv", type=Path, default=ROOT / "data/census/block_vap_2020_nc.csv")
    p.add_argument("--out-dir", type=Path, default=ROOT / "data/reports")
    p.add_argument(
        "--out-weights-json",
        type=Path,
        default=ROOT / "data/mappings/sbe2006_to_modern_district_weights.json",
    )
    p.add_argument("--top-n", type=int, default=25)
    return p.parse_args()


def clean_precinct_id(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.upper().str.replace(r"\s+", " ", regex=True)


def clean_block(series: pd.Series) -> pd.Series:
    cleaned = series.fillna("").astype(str).str.strip()
    return cleaned.where(cleaned == "", cleaned.str.zfill(15))


def district_code(value: object, width: int) -> str:
    raw = str(value).strip()
    num = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
    if pd.notna(num):
        return f"{int(num):0{width}d}"
    return raw


def district_label(value: object, prefix: str, width: int) -> str:
    return f"{prefix}-{district_code(value, width)}"


def district_name(value: object, spec: DistrictSpec) -> str:
    code = district_code(value, spec.district_width)
    number = str(int(code)) if code.isdigit() else code
    return spec.district_name_template.format(prefix=spec.district_prefix, code=code, number=number)


def relative_or_missing(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_sbe_bridge(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    required = {"block_geoid20", "precinct_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    out = df[["block_geoid20", "precinct_id"]].copy()
    out["block_geoid20"] = clean_block(out["block_geoid20"])
    out["sbe_precinct_id"] = clean_precinct_id(out["precinct_id"])
    out = out[(out["block_geoid20"] != "") & (out["sbe_precinct_id"] != "")]
    out = out.drop(columns=["precinct_id"]).drop_duplicates("block_geoid20")
    return out


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


def load_assignment(spec: DistrictSpec) -> pd.DataFrame:
    df = pd.read_csv(spec.assignment_path, dtype=str)
    missing = {spec.block_col, spec.district_col} - set(df.columns)
    if missing:
        raise ValueError(f"{spec.assignment_path} missing columns: {sorted(missing)}")
    out = df[[spec.block_col, spec.district_col]].copy()
    out.columns = ["block_geoid20", "district"]
    out["block_geoid20"] = clean_block(out["block_geoid20"])
    out["district"] = out["district"].astype(str).str.strip()
    out = out[(out["block_geoid20"] != "") & (out["district"] != "")]
    out = out.drop_duplicates("block_geoid20")
    district_values = out["district"].drop_duplicates()
    labels = {
        value: district_label(value, spec.district_prefix, spec.district_width)
        for value in district_values
    }
    names = {value: district_name(value, spec) for value in district_values}
    out["district_label"] = out["district"].map(labels)
    out["district_name"] = out["district"].map(names)
    return out


def summarize_scope(
    spec: DistrictSpec,
    sbe: pd.DataFrame,
    assignment: pd.DataFrame,
    vap: pd.DataFrame,
    sbe_blocks_total: int,
    sbe_precincts_total: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    joined = sbe.merge(assignment, on="block_geoid20", how="inner").merge(vap, on="block_geoid20", how="left")
    joined["vap_count"] = joined["vap_count"].fillna(0.0)
    matched_blocks = len(joined)

    grouped = (
        joined.groupby(["sbe_precinct_id", "district", "district_label", "district_name"], as_index=False)
        .agg(block_count=("block_geoid20", "nunique"), vap_count=("vap_count", "sum"))
    )
    block_totals = (
        joined.groupby("sbe_precinct_id", as_index=False)
        .agg(sbe_block_total=("block_geoid20", "nunique"), sbe_vap_total=("vap_count", "sum"))
    )
    grouped = grouped.merge(block_totals, on="sbe_precinct_id", how="left")
    grouped["block_share"] = grouped["block_count"] / grouped["sbe_block_total"]

    grouped["weight"] = grouped["vap_count"]
    grouped["weight_source"] = "vap"
    zero_vap = grouped["sbe_vap_total"] <= 0
    grouped.loc[zero_vap, "weight"] = grouped.loc[zero_vap, "block_count"].astype(float)
    grouped.loc[zero_vap, "weight_source"] = "block_count"
    weight_totals = grouped.groupby("sbe_precinct_id")["weight"].transform("sum")
    grouped["share"] = grouped["weight"] / weight_totals.replace(0, pd.NA)

    grouped = grouped.sort_values(
        ["sbe_precinct_id", "share", "block_share", "district_label"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)
    grouped["rank"] = grouped.groupby("sbe_precinct_id").cumcount() + 1
    grouped["is_dominant"] = grouped["rank"] == 1
    grouped.insert(0, "scope", spec.scope)
    grouped.insert(1, "target_year", spec.target_year)
    grouped.insert(2, "district_type", spec.district_type)
    grouped.insert(3, "plan_id", spec.plan_id)

    district_counts = grouped.groupby("sbe_precinct_id")["district_label"].nunique()
    split_precincts = int((district_counts > 1).sum())
    dominant = grouped[grouped["is_dominant"]].copy()
    summary = {
        "scope": spec.scope,
        "target_year": spec.target_year,
        "district_type": spec.district_type,
        "plan_id": spec.plan_id,
        "assignment_path": relative_or_missing(spec.assignment_path),
        "assignment_exists": spec.assignment_path.exists(),
        "geometry_path": relative_or_missing(spec.geometry_path),
        "geometry_exists": bool(spec.geometry_path and spec.geometry_path.exists()),
        "sbe2006_precincts_total": sbe_precincts_total,
        "sbe2006_blocks_total": sbe_blocks_total,
        "assignment_blocks_total": len(assignment),
        "matched_blocks": matched_blocks,
        "unmatched_sbe_blocks": sbe_blocks_total - matched_blocks,
        "block_coverage_pct": round(float(matched_blocks / sbe_blocks_total * 100), 6),
        "precincts_with_assignment": int(block_totals["sbe_precinct_id"].nunique()),
        "districts_observed": int(grouped["district_label"].nunique()),
        "split_precincts": split_precincts,
        "split_precinct_pct": round(float(split_precincts / sbe_precincts_total * 100), 4),
        "dominant_share_lt_0_90_precincts": int((dominant["share"] < 0.90).sum()),
        "dominant_share_lt_0_75_precincts": int((dominant["share"] < 0.75).sum()),
        "zero_vap_precincts_using_block_weights": int(
            (grouped.groupby("sbe_precinct_id")["weight_source"].first() == "block_count").sum()
        ),
    }
    return grouped, summary


def build_split_examples(detail: pd.DataFrame, top_n: int) -> pd.DataFrame:
    rows = []
    for (scope, precinct), g in detail.groupby(["scope", "sbe_precinct_id"], sort=False):
        if len(g) <= 1:
            continue
        ordered = g.sort_values(["share", "block_share", "district_label"], ascending=[False, False, True])
        shares = "; ".join(f"{r.district_label}={r.share:.4f}" for r in ordered.itertuples())
        rows.append(
            {
                "scope": scope,
                "target_year": int(ordered["target_year"].iloc[0]),
                "district_type": ordered["district_type"].iloc[0],
                "sbe_precinct_id": precinct,
                "district_count": int(ordered["district_label"].nunique()),
                "top_district_label": ordered["district_label"].iloc[0],
                "top_share": float(ordered["share"].iloc[0]),
                "second_share": float(ordered["share"].iloc[1]) if len(ordered) > 1 else 0.0,
                "top_block_share": float(ordered["block_share"].iloc[0]),
                "sbe_block_total": int(ordered["sbe_block_total"].iloc[0]),
                "sbe_vap_total": float(ordered["sbe_vap_total"].iloc[0]),
                "district_shares": shares,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["split_gap"] = out["top_share"] - out["second_share"]
    return (
        out.sort_values(["scope", "district_count", "top_share", "sbe_precinct_id"], ascending=[True, False, True, True])
        .groupby("scope", as_index=False)
        .head(top_n)
        .reset_index(drop=True)
    )


def build_weights_payload(detail: pd.DataFrame, summary: pd.DataFrame, *, source_block_map: Path, vap_csv: Path) -> dict:
    """Build a compact SBE 2006 precinct -> modern district weights payload."""
    scopes: dict[str, dict] = {}
    summary_by_scope = {str(r["scope"]): r for _, r in summary.iterrows()}
    for scope, g in detail.groupby("scope", sort=True):
        sr = summary_by_scope.get(str(scope), {})
        precincts: dict[str, list[dict]] = {}
        for precinct, pg in g.groupby("sbe_precinct_id", sort=True):
            entries: list[dict] = []
            ordered = pg.sort_values(["share", "block_share", "district_label"], ascending=[False, False, True])
            for r in ordered.itertuples():
                share = float(r.share)
                if share <= 0:
                    continue
                entries.append(
                    {
                        "district": str(r.district),
                        "district_label": str(r.district_label),
                        "district_name": str(r.district_name),
                        "share": share,
                        "block_share": float(r.block_share),
                        "block_count": int(r.block_count),
                        "vap_count": float(r.vap_count),
                        "weight_source": str(r.weight_source),
                    }
                )
            if entries:
                precincts[str(precinct)] = entries

        scopes[str(scope)] = {
            "scope": str(scope),
            "target_year": int(sr.get("target_year", g["target_year"].iloc[0])),
            "district_type": str(sr.get("district_type", g["district_type"].iloc[0])),
            "plan_id": str(sr.get("plan_id", g["plan_id"].iloc[0])),
            "assignment_path": str(sr.get("assignment_path", "")),
            "geometry_path": str(sr.get("geometry_path", "")),
            "matched_blocks": int(sr.get("matched_blocks", 0)),
            "sbe2006_blocks_total": int(sr.get("sbe2006_blocks_total", 0)),
            "sbe2006_precincts_total": int(sr.get("sbe2006_precincts_total", len(precincts))),
            "block_coverage_pct": float(sr.get("block_coverage_pct", 0.0)),
            "split_precincts": int(sr.get("split_precincts", 0)),
            "zero_vap_precincts_using_block_weights": int(sr.get("zero_vap_precincts_using_block_weights", 0)),
            "precincts": precincts,
        }

    return {
        "schema": "sbe2006_to_modern_district_weights.v1",
        "description": "VAP-weighted SBE 2006 precinct shares into modern district plans.",
        "source_block_map": relative_or_missing(source_block_map),
        "vap_csv": relative_or_missing(vap_csv),
        "scope_sets": {
            "2022": {
                "state_house": "2022_state_house_mqp",
                "state_senate": "2022_state_senate_mqp",
                "congressional": "2022_congressional_cd118",
            },
            "2024": {
                "state_house": "2024_state_house",
                "state_senate": "2024_state_senate",
                "congressional": "2024_congressional_cd119",
            },
            "2026": {
                "congressional": "2026_congressional_sl2025_95",
            },
        },
        "scopes": scopes,
    }


def main() -> None:
    args = parse_args()
    sbe = load_sbe_bridge(args.sbe2006_block_map)
    vap = load_vap(args.vap_csv)
    sbe_blocks_total = len(sbe)
    sbe_precincts_total = int(sbe["sbe_precinct_id"].nunique())
    details = []
    summaries = []

    for spec in DEFAULT_SPECS:
        if not spec.assignment_path.exists():
            print(f"Skipping missing assignment: {relative_or_missing(spec.assignment_path)}")
            continue
        assignment = load_assignment(spec)
        detail, summary = summarize_scope(
            spec,
            sbe,
            assignment,
            vap,
            sbe_blocks_total=sbe_blocks_total,
            sbe_precincts_total=sbe_precincts_total,
        )
        details.append(detail)
        summaries.append(summary)
        print(
            f"{spec.scope}: matched {summary['matched_blocks']:,}/{summary['sbe2006_blocks_total']:,} "
            f"blocks; split precincts={summary['split_precincts']:,}"
        )

    if not details:
        raise SystemExit("No district assignment inputs were available.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    detail_out = args.out_dir / "sbe2006_to_modern_district_bridge_detail.csv"
    summary_out = args.out_dir / "sbe2006_to_modern_district_bridge_summary.csv"
    splits_out = args.out_dir / "sbe2006_to_modern_district_bridge_top_splits.csv"

    all_detail = pd.concat(details, ignore_index=True)
    summary_df = pd.DataFrame(summaries)
    split_examples = build_split_examples(all_detail, args.top_n)

    all_detail.to_csv(detail_out, index=False)
    summary_df.to_csv(summary_out, index=False)
    split_examples.to_csv(splits_out, index=False)
    weights_payload = build_weights_payload(
        all_detail,
        summary_df,
        source_block_map=args.sbe2006_block_map,
        vap_csv=args.vap_csv,
    )
    args.out_weights_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_weights_json.write_text(json.dumps(weights_payload, separators=(",", ":")) + "\n", encoding="utf-8")

    print(f"Wrote {len(all_detail):,} detail rows -> {detail_out}")
    print(f"Wrote {len(summary_df):,} summary rows -> {summary_out}")
    print(f"Wrote {len(split_examples):,} top split rows -> {splits_out}")
    print(f"Wrote {len(weights_payload['scopes']):,} weight scopes -> {args.out_weights_json}")


if __name__ == "__main__":
    main()
