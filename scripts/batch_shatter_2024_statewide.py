"""
Batch shatter 2024 statewide contests to block level (VAP-weighted),
then aggregate to NC 2022 House/Senate and CD118 districts.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import zipfile

import pandas as pd

from shatter_precinct_votes_vap import (
    aggregate_to_districts,
    load_crosswalk,
    load_vap,
    shatter_votes,
)


OFFICES = {
    "US PRESIDENT": "president",
    "US SENATE": "us_senate",
    "NC GOVERNOR": "governor",
    "NC LIEUTENANT GOVERNOR": "lieutenant_governor",
    "NC ATTORNEY GENERAL": "attorney_general",
    "NC AUDITOR": "auditor",
    "NC COMMISSIONER OF AGRICULTURE": "agriculture_commissioner",
    "NC COMMISSIONER OF LABOR": "labor_commissioner",
    "NC COMMISSIONER OF INSURANCE": "insurance_commissioner",
    "NC SECRETARY OF STATE": "secretary_of_state",
    "NC TREASURER": "treasurer",
    "NC SUPERINTENDENT OF PUBLIC INSTRUCTION": "superintendent",
}

COUNCIL_OF_STATE_OFFICES = {
    "NC GOVERNOR": "governor",
    "NC LIEUTENANT GOVERNOR": "lieutenant_governor",
    "NC ATTORNEY GENERAL": "attorney_general",
    "NC AUDITOR": "auditor",
    "NC COMMISSIONER OF AGRICULTURE": "agriculture_commissioner",
    "NC COMMISSIONER OF LABOR": "labor_commissioner",
    "NC COMMISSIONER OF INSURANCE": "insurance_commissioner",
    "NC SECRETARY OF STATE": "secretary_of_state",
    "NC TREASURER": "treasurer",
    "NC SUPERINTENDENT OF PUBLIC INSTRUCTION": "superintendent",
}


NON_GEO_FLAGS = [
    "ABSENTEE",
    "ONE STOP",
    "ONE-STOP",
    "EARLY",
    "EV ",
    "EV-",
    "EV_",
    "PROVISIONAL",
    "CURBSIDE",
    "MAIL",
]


def is_non_geographic_precinct(name: str) -> bool:
    t = str(name).strip().upper()
    return any(flag in t for flag in NON_GEO_FLAGS)


def slugify_office(name: str) -> str:
    s = str(name).strip().lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    key = "".join(out).strip("_")
    while "__" in key:
        key = key.replace("__", "_")
    return key


def select_offices(src: pd.DataFrame, office_set: str) -> dict[str, str]:
    if office_set == "default":
        return OFFICES.copy()
    if office_set == "council_of_state":
        return COUNCIL_OF_STATE_OFFICES.copy()
    if office_set == "statewide_judicial":
        offices = sorted(
            {
                o
                for o in src["office"].dropna().astype(str).unique()
                if o.startswith("NC SUPREME COURT ") or o.startswith("NC COURT OF APPEALS ")
            }
        )
        return {o: slugify_office(o) for o in offices}
    if office_set == "council_and_statewide_judicial":
        out = COUNCIL_OF_STATE_OFFICES.copy()
        judicial = select_offices(src, "statewide_judicial")
        for office, key in judicial.items():
            if key in out.values():
                key = f"{key}_judicial"
            out[office] = key
        return out
    raise ValueError(f"Unknown office_set: {office_set}")


def _ensure_extracted(zip_path: Path, out_dir: Path, expected_name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / expected_name
    if out_path.exists():
        return out_path
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_dir)
    if not out_path.exists():
        raise FileNotFoundError(f"Expected extracted file not found: {out_path}")
    return out_path


def load_district_map(path: Path, block_col: str, district_col: str) -> pd.DataFrame:
    d = pd.read_csv(path, dtype=str)
    d.columns = [str(c).strip() for c in d.columns]
    block_col = block_col.strip()
    district_col = district_col.strip()
    out = d[[block_col, district_col]].copy()
    out.columns = ["block_geoid20", "district"]
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.strip().str.zfill(15)
    out["district"] = out["district"].astype(str).str.strip()
    # Normalize numeric district labels so values like "01" and "1" collapse.
    out["district"] = out["district"].str.replace(r"\.0$", "", regex=True)
    numeric_mask = out["district"].str.match(r"^\d+$", na=False)
    out.loc[numeric_mask, "district"] = out.loc[numeric_mask, "district"].str.lstrip("0")
    out.loc[out["district"] == "", "district"] = "0"
    return out.dropna().drop_duplicates(subset=["block_geoid20"], keep="first")


def build_county_shares(
    crosswalk_df: pd.DataFrame,
    vap_df: pd.DataFrame,
    district_map: pd.DataFrame,
) -> pd.DataFrame:
    cw = crosswalk_df.copy()
    cw["county"] = cw["precinct_id"].astype(str).str.split(" - ").str[0].str.strip().str.upper()
    v = vap_df.copy()
    v["vap_count"] = pd.to_numeric(v["vap_count"], errors="coerce").fillna(0.0)
    m = (
        cw[["block_geoid20", "county"]]
        .merge(v[["block_geoid20", "vap_count"]], on="block_geoid20", how="left")
        .merge(district_map[["block_geoid20", "district"]], on="block_geoid20", how="inner")
    )
    m["vap_count"] = m["vap_count"].fillna(0.0)
    g = m.groupby(["county", "district"], as_index=False)["vap_count"].sum()
    den = g.groupby("county", as_index=False)["vap_count"].sum().rename(columns={"vap_count": "county_vap"})
    g = g.merge(den, on="county", how="left")
    g["share"] = g["vap_count"] / g["county_vap"]
    return g[["county", "district", "share"]]


def apply_unmatched_county_fallback(
    *,
    district_df: pd.DataFrame,
    results_df: pd.DataFrame,
    matched_precincts: set[str],
    county_shares: pd.DataFrame,
) -> tuple[pd.DataFrame, float]:
    d = district_df.copy()
    d["district"] = d["district"].astype(str).str.strip()
    d["votes_rounded"] = pd.to_numeric(d["votes_rounded"], errors="coerce").fillna(0.0)
    base = d.set_index("district")["votes_rounded"].to_dict()

    r = results_df.copy()
    r["precinct_id"] = r["precinct_id"].astype(str).str.strip().str.upper()
    r["votes"] = pd.to_numeric(r["votes"], errors="coerce").fillna(0.0)
    r["county"] = r["precinct_id"].str.split(" - ").str[0].str.strip().str.upper()
    unmatched = r[~r["precinct_id"].isin(matched_precincts)].copy()
    if unmatched.empty:
        out = d.sort_values("district").copy()
        out["votes_rounded"] = out["votes_rounded"].round().astype(int)
        return out, 0.0

    u = unmatched.groupby("county", as_index=False)["votes"].sum().rename(columns={"votes": "unmatched_votes"})
    alloc = u.merge(county_shares, on="county", how="left")
    alloc = alloc.dropna(subset=["district", "share"]).copy()
    alloc["alloc_votes"] = alloc["unmatched_votes"] * alloc["share"]
    fallback_votes = float(alloc["alloc_votes"].sum())

    add = alloc.groupby("district", as_index=False)["alloc_votes"].sum()
    for _, row in add.iterrows():
        dist = str(row["district"]).strip()
        base[dist] = float(base.get(dist, 0.0)) + float(row["alloc_votes"])

    out = pd.DataFrame({"district": list(base.keys()), "votes_rounded": list(base.values())})
    out["votes_rounded"] = out["votes_rounded"].round().astype(int)
    out = out.sort_values("district")
    return out, fallback_votes


def build_county_fallback_diagnostic(
    *,
    results_df: pd.DataFrame,
    matched_precincts: set[str],
    house_shares: pd.DataFrame,
    senate_shares: pd.DataFrame,
    cd_shares: pd.DataFrame,
) -> pd.DataFrame:
    r = results_df.copy()
    r["precinct_id"] = r["precinct_id"].astype(str).str.strip().str.upper()
    r["votes"] = pd.to_numeric(r["votes"], errors="coerce").fillna(0.0)
    r["county"] = r["precinct_id"].str.split(" - ").str[0].str.strip().str.upper()
    unmatched = r[~r["precinct_id"].isin(matched_precincts)].copy()
    if unmatched.empty:
        return pd.DataFrame(
            columns=[
                "county",
                "unmatched_votes",
                "allocated_house",
                "allocated_senate",
                "allocated_cd",
                "unallocated_house",
                "unallocated_senate",
                "unallocated_cd",
            ]
        )
    u = unmatched.groupby("county", as_index=False)["votes"].sum().rename(columns={"votes": "unmatched_votes"})
    h = house_shares.groupby("county", as_index=False)["share"].sum().rename(columns={"share": "house_share_sum"})
    s = senate_shares.groupby("county", as_index=False)["share"].sum().rename(columns={"share": "senate_share_sum"})
    c = cd_shares.groupby("county", as_index=False)["share"].sum().rename(columns={"share": "cd_share_sum"})
    out = u.merge(h, on="county", how="left").merge(s, on="county", how="left").merge(c, on="county", how="left")
    out["house_share_sum"] = out["house_share_sum"].fillna(0.0)
    out["senate_share_sum"] = out["senate_share_sum"].fillna(0.0)
    out["cd_share_sum"] = out["cd_share_sum"].fillna(0.0)
    out["allocated_house"] = out["unmatched_votes"] * out["house_share_sum"]
    out["allocated_senate"] = out["unmatched_votes"] * out["senate_share_sum"]
    out["allocated_cd"] = out["unmatched_votes"] * out["cd_share_sum"]
    out["unallocated_house"] = out["unmatched_votes"] - out["allocated_house"]
    out["unallocated_senate"] = out["unmatched_votes"] - out["allocated_senate"]
    out["unallocated_cd"] = out["unmatched_votes"] - out["allocated_cd"]
    return out[
        [
            "county",
            "unmatched_votes",
            "allocated_house",
            "allocated_senate",
            "allocated_cd",
            "unallocated_house",
            "unallocated_senate",
            "unallocated_cd",
        ]
    ].sort_values("county")


def build_results_for_office(src: pd.DataFrame, office_name: str) -> pd.DataFrame:
    df = src[src["office"] == office_name].copy()
    if df.empty:
        return pd.DataFrame(columns=["precinct_id", "votes"])
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0.0)
    df["county"] = df["county"].astype(str).str.strip().str.upper()
    df["precinct"] = df["precinct"].astype(str).str.strip().str.upper()
    df["candidate"] = df["candidate"].astype(str).str.strip()
    df["precinct_id"] = (
        df["county"].astype(str).str.strip().str.upper()
        + " - "
        + df["precinct"].astype(str).str.strip().str.upper()
    )
    df["non_geo"] = df["precinct"].map(is_non_geographic_precinct)

    geo = df[~df["non_geo"]].copy()
    non_geo = df[df["non_geo"]].copy()
    if non_geo.empty:
        if geo.empty:
            return pd.DataFrame(columns=["precinct_id", "votes"])
        return geo.groupby("precinct_id", as_index=False)["votes"].sum()

    # Candidate-performance proportional allocation by county.
    geo_cand = geo.groupby(["county", "candidate", "precinct_id"], as_index=False)["votes"].sum()
    cand_den = geo_cand.groupby(["county", "candidate"], as_index=False)["votes"].sum().rename(
        columns={"votes": "cand_geo_total"}
    )
    non_geo_cand = non_geo.groupby(["county", "candidate"], as_index=False)["votes"].sum().rename(
        columns={"votes": "non_geo_votes"}
    )
    alloc = geo_cand.merge(cand_den, on=["county", "candidate"], how="left").merge(
        non_geo_cand, on=["county", "candidate"], how="left"
    )
    alloc["non_geo_votes"] = alloc["non_geo_votes"].fillna(0.0)
    alloc["alloc"] = 0.0
    m = alloc["cand_geo_total"] > 0
    alloc.loc[m, "alloc"] = alloc.loc[m, "non_geo_votes"] * (alloc.loc[m, "votes"] / alloc.loc[m, "cand_geo_total"])

    # Edge fallback: if candidate has non-geo votes but no geo denominator, allocate
    # by county-wide geographic share across all candidates.
    miss = non_geo_cand.merge(cand_den, on=["county", "candidate"], how="left")
    miss = miss[(miss["cand_geo_total"].isna()) & (miss["non_geo_votes"] > 0)].copy()
    if not miss.empty:
        county_geo = geo.groupby(["county", "precinct_id"], as_index=False)["votes"].sum()
        county_den = county_geo.groupby("county", as_index=False)["votes"].sum().rename(columns={"votes": "county_geo_total"})
        cshare = county_geo.merge(county_den, on="county", how="left")
        cshare["share"] = cshare["votes"] / cshare["county_geo_total"]
        miss_alloc = miss.merge(cshare[["county", "precinct_id", "share"]], on="county", how="left")
        miss_alloc["alloc"] = miss_alloc["non_geo_votes"] * miss_alloc["share"].fillna(0.0)
        alloc_extra = miss_alloc.groupby("precinct_id", as_index=False)["alloc"].sum()
    else:
        alloc_extra = pd.DataFrame(columns=["precinct_id", "alloc"])

    alloc_main = alloc.groupby("precinct_id", as_index=False)["alloc"].sum()
    alloc_all = pd.concat([alloc_main, alloc_extra], ignore_index=True).groupby("precinct_id", as_index=False)["alloc"].sum()
    geo_tot = geo.groupby("precinct_id", as_index=False)["votes"].sum()
    out = geo_tot.merge(alloc_all, on="precinct_id", how="left")
    out["alloc"] = out["alloc"].fillna(0.0)
    out["votes"] = out["votes"] + out["alloc"]
    out["votes"] = out["votes"].map(lambda v: Decimal(str(v)))
    return out[["precinct_id", "votes"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch shatter NC 2024 statewide contests.")
    parser.add_argument(
        "--results-csv",
        type=Path,
        default=Path("data/2024/20241105__nc__general__precinct.csv"),
    )
    parser.add_argument(
        "--block-precinct-crosswalk",
        type=Path,
        default=Path("data/crosswalks/block20_to_precinct.csv"),
    )
    parser.add_argument(
        "--vap-csv",
        type=Path,
        default=Path("data/census/block_vap_2020_nc.csv"),
    )
    parser.add_argument(
        "--house-zip",
        type=Path,
        default=Path("data/census/block files/SL 2022-4 House - Block Assignment File.zip"),
    )
    parser.add_argument(
        "--senate-zip",
        type=Path,
        default=Path("data/census/block files/SL 2022-2 Senate - Block Assignment File.zip"),
    )
    parser.add_argument(
        "--cd-file",
        type=Path,
        default=Path("data/census/block files/NC_CD118.txt"),
    )
    parser.add_argument(
        "--extract-dir",
        type=Path,
        default=Path("data/tmp/block_assign_extract"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/tmp/shatter/batch_2024_statewide"),
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=28,
    )
    parser.add_argument(
        "--county-fallback",
        action="store_true",
        help="Allocate unmatched precinct votes by county VAP district shares.",
    )
    parser.add_argument(
        "--office-set",
        choices=["default", "council_of_state", "statewide_judicial", "council_and_statewide_judicial"],
        default="default",
        help="Which office group to process.",
    )
    args = parser.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    house_csv = _ensure_extracted(args.house_zip, args.extract_dir, "SL 2022-4.csv")
    senate_csv = _ensure_extracted(args.senate_zip, args.extract_dir, "SL 2022-2.csv")

    src = pd.read_csv(args.results_csv, dtype=str, low_memory=False)
    crosswalk_df = load_crosswalk(args.block_precinct_crosswalk, "precinct_id", "block_geoid20")
    vap_df = load_vap(args.vap_csv, "block_geoid20", "vap_count")
    matched_precinct_set = set(crosswalk_df["precinct_id"].astype(str).str.strip().str.upper().unique())
    house_map = load_district_map(house_csv, "Block", "District")
    senate_map = load_district_map(senate_csv, "Block", "District")
    cd_map = load_district_map(args.cd_file, "GEOID", "CDFP")
    house_shares = build_county_shares(crosswalk_df, vap_df, house_map)
    senate_shares = build_county_shares(crosswalk_df, vap_df, senate_map)
    cd_shares = build_county_shares(crosswalk_df, vap_df, cd_map)

    summary_rows = []
    offices_to_run = select_offices(src, args.office_set)

    for office_name, office_key in offices_to_run.items():
        print(f"Processing {office_name} -> {office_key}")
        results_df = build_results_for_office(src, office_name)
        if results_df.empty:
            print("  no rows, skipping")
            continue

        shattered, audit = shatter_votes(
            results_df=results_df,
            crosswalk_df=crosswalk_df,
            vap_df=vap_df,
            precision=args.precision,
        )

        office_dir = out_dir / office_key
        office_dir.mkdir(parents=True, exist_ok=True)

        # Save audit and block-level (stringified decimals).
        out_blocks = shattered[
            ["precinct_id", "block_geoid20", "vap_count", "total_precinct_vap", "block_weight", "votes", "block_votes_raw"]
        ].copy()
        for col in ["vap_count", "total_precinct_vap", "block_weight", "votes", "block_votes_raw"]:
            out_blocks[col] = out_blocks[col].map(str)
        out_blocks.to_csv(office_dir / "block_votes.csv", index=False)

        out_audit = audit.copy()
        for col in ["precinct_votes", "block_votes_sum", "total_precinct_vap", "delta"]:
            out_audit[col] = out_audit[col].map(str)
        out_audit.to_csv(office_dir / "audit.csv", index=False)

        house = aggregate_to_districts(shattered, house_csv, "Block", "District")
        senate = aggregate_to_districts(shattered, senate_csv, "Block", "District")
        cd = aggregate_to_districts(shattered, args.cd_file, "GEOID", "CDFP")

        fallback_house = 0.0
        fallback_senate = 0.0
        fallback_cd = 0.0
        if args.county_fallback:
            house, fallback_house = apply_unmatched_county_fallback(
                district_df=house,
                results_df=results_df,
                matched_precincts=matched_precinct_set,
                county_shares=house_shares,
            )
            senate, fallback_senate = apply_unmatched_county_fallback(
                district_df=senate,
                results_df=results_df,
                matched_precincts=matched_precinct_set,
                county_shares=senate_shares,
            )
            cd, fallback_cd = apply_unmatched_county_fallback(
                district_df=cd,
                results_df=results_df,
                matched_precincts=matched_precinct_set,
                county_shares=cd_shares,
            )
            county_diag = build_county_fallback_diagnostic(
                results_df=results_df,
                matched_precincts=matched_precinct_set,
                house_shares=house_shares,
                senate_shares=senate_shares,
                cd_shares=cd_shares,
            )
            county_diag.to_csv(office_dir / "county_fallback_diagnostic.csv", index=False)

        for df, name in [(house, "state_house"), (senate, "state_senate"), (cd, "cd118")]:
            out = df.copy()
            if "block_votes_raw" not in out.columns:
                out["block_votes_raw"] = pd.to_numeric(out["votes_rounded"], errors="coerce").fillna(0.0)
            out["block_votes_raw"] = out["block_votes_raw"].map(str)
            out.to_csv(office_dir / f"{name}.csv", index=False)

        coverage_pct = round(len(audit) / len(results_df) * 100.0, 2) if len(results_df) else 0.0
        summary_rows.append(
            {
                "office": office_name,
                "office_key": office_key,
                "source_precincts": int(len(results_df)),
                "matched_precincts": int(len(audit)),
                "coverage_pct": coverage_pct,
                "house_districts": int(house["district"].nunique()),
                "senate_districts": int(senate["district"].nunique()),
                "cd_districts": int(cd["district"].nunique()),
                "fallback_votes_house": round(fallback_house, 2),
                "fallback_votes_senate": round(fallback_senate, 2),
                "fallback_votes_cd": round(fallback_cd, 2),
            }
        )

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out_dir / "summary.csv", index=False)
    print(f"Wrote batch outputs to {out_dir}")
    print(f"Wrote summary: {out_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
