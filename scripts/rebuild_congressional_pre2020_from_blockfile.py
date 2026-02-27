from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd


OFFICE_TO_CONTEST_TYPE = {
    "PRES": "president",
    "SEN": "us_senate",
    "GOV": "governor",
    "AG": "attorney_general",
    "AUD": "auditor",
    "LTG": "lieutenant_governor",
    "SOS": "secretary_of_state",
    "TREAS": "treasurer",
}


def calculate_competitiveness(margin_pct: float) -> str:
    abs_margin = abs(float(margin_pct))
    if abs_margin < 0.5:
        return "#f7f7f7"
    rep_win = float(margin_pct) > 0
    if abs_margin >= 40:
        return "#67000d" if rep_win else "#08306b"
    if abs_margin >= 30:
        return "#a50f15" if rep_win else "#08519c"
    if abs_margin >= 20:
        return "#cb181d" if rep_win else "#3182bd"
    if abs_margin >= 10:
        return "#ef3b2c" if rep_win else "#6baed6"
    if abs_margin >= 5.5:
        return "#fb6a4a" if rep_win else "#9ecae1"
    if abs_margin >= 1:
        return "#fcae91" if rep_win else "#c6dbef"
    return "#fee8c8" if rep_win else "#e1f5fe"


def load_cd118_block_map(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    if "block_geoid20" not in df.columns or "district" not in df.columns:
        raise ValueError(f"Expected columns block_geoid20,district in {path}")
    out = df[["block_geoid20", "district"]].copy()
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.strip().str.zfill(15)
    out["district"] = out["district"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    m = out["district"].str.match(r"^\d+$", na=False)
    out.loc[m, "district"] = out.loc[m, "district"].str.lstrip("0")
    out.loc[out["district"] == "", "district"] = "0"
    return out.drop_duplicates(subset=["block_geoid20"], keep="first")


def infer_candidate_names(existing_path: Path) -> tuple[str, str]:
    if not existing_path.exists():
        return "", ""
    try:
        payload = json.loads(existing_path.read_text(encoding="utf-8"))
        results = (((payload.get("general") or {}).get("results")) or {})
        for _, row in results.items():
            dc = str(row.get("dem_candidate") or "").strip()
            rc = str(row.get("rep_candidate") or "").strip()
            if dc or rc:
                return dc, rc
    except Exception:
        return "", ""
    return "", ""


def build_payload(
    *,
    year: int,
    contest_type: str,
    office_label: str,
    dem_candidate: str,
    rep_candidate: str,
    dem_map: dict[str, int],
    rep_map: dict[str, int],
    oth_map: dict[str, int],
    source: str,
) -> dict:
    keys = sorted(set(dem_map) | set(rep_map) | set(oth_map), key=lambda x: (int(x) if str(x).isdigit() else x))
    results = {}
    for k in keys:
        dem = int(dem_map.get(k, 0))
        rep = int(rep_map.get(k, 0))
        oth = int(oth_map.get(k, 0))
        total_votes = dem + rep + oth
        margin = rep - dem
        margin_pct = (margin / total_votes * 100.0) if total_votes else 0.0
        winner = "REP" if margin > 0 else "DEM" if margin < 0 else "TIE"
        results[str(k)] = {
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": oth,
            "total_votes": total_votes,
            "dem_candidate": dem_candidate,
            "rep_candidate": rep_candidate,
            "margin": margin,
            "margin_pct": round(margin_pct, 2),
            "winner": winner,
            "competitiveness": {"color": calculate_competitiveness(margin_pct)},
        }
    return {
        "year": int(year),
        "scope": "congressional",
        "contest_type": contest_type,
        "meta": {
            "match_coverage_pct": 0.0,
            "matched_precinct_keys": 0,
            "total_precinct_keys": 0,
            "source": source,
            "office": office_label,
        },
        "general": {"results": results},
    }


def rebuild_manifest(out_dir: Path) -> None:
    manifest = []
    for p in sorted(out_dir.glob("*.json")):
        if p.name == "manifest.json":
            continue
        parts = p.stem.split("_")
        if len(parts) < 3:
            continue
        if parts[0] == "state" and len(parts) >= 4:
            scope = "_".join(parts[0:2])
            contest_type = "_".join(parts[2:-1])
        else:
            scope = parts[0]
            contest_type = "_".join(parts[1:-1])
        try:
            year = int(parts[-1])
        except ValueError:
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            districts = len(((payload.get("general") or {}).get("results")) or {})
        except Exception:
            districts = 0
        manifest.append(
            {"year": year, "scope": scope, "contest_type": contest_type, "file": p.name, "districts": districts}
        )
    manifest.sort(key=lambda x: (x["year"], x["scope"], x["contest_type"]))
    (out_dir / "manifest.json").write_text(json.dumps({"files": manifest}, indent=2), encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    blockfile = repo_root / "data" / "Election_Data_Block_NC.v07" / "election_data_block_NC.v07.csv"
    cd_map_path = repo_root / "data" / "crosswalks" / "block20_to_cd118.csv"
    out_dir = repo_root / "data" / "district_contests"

    if not blockfile.exists():
        raise SystemExit(f"Missing blockfile: {blockfile}")
    if not cd_map_path.exists():
        raise SystemExit(f"Missing CD map: {cd_map_path}")

    cd_map = load_cd118_block_map(cd_map_path)
    cd_lookup = dict(zip(cd_map["block_geoid20"], cd_map["district"]))

    header = pd.read_csv(blockfile, nrows=0).columns.tolist()
    pat = re.compile(r"^E_(\d{2})_([A-Z0-9-]+)_(Total|Dem|Rep)$")

    # Collect contests available in the blockfile that map into our app contest_type space.
    contests: dict[tuple[int, str], dict[str, str]] = {}
    for c in header:
        m = pat.match(str(c))
        if not m:
            continue
        yy, office, part = m.groups()
        year = 2000 + int(yy)
        if year >= 2020:
            continue
        if office not in OFFICE_TO_CONTEST_TYPE:
            continue
        key = (year, office)
        contests.setdefault(key, {})[part] = c

    # Keep only full triplets.
    contests = {k: v for k, v in contests.items() if {"Total", "Dem", "Rep"} <= set(v.keys())}
    if not contests:
        print("No pre-2020 contests found in blockfile.")
        return

    usecols = ["GEOID"] + sorted({col for v in contests.values() for col in v.values()})

    # Accumulators: (year, office) -> district -> sums
    sums_total: dict[tuple[int, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sums_dem: dict[tuple[int, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sums_rep: dict[tuple[int, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for chunk in pd.read_csv(blockfile, usecols=usecols, dtype=str, chunksize=400_000):
        chunk = chunk.fillna("")
        chunk["GEOID"] = chunk["GEOID"].astype(str).str.strip().str.zfill(15)
        chunk["district"] = chunk["GEOID"].map(cd_lookup)
        chunk = chunk[chunk["district"].notna()].copy()
        if chunk.empty:
            continue

        # Convert all election columns to numeric once.
        for col in usecols:
            if col == "GEOID":
                continue
            if col == "district":
                continue
            chunk[col] = pd.to_numeric(chunk[col], errors="coerce").fillna(0.0)

        g = chunk.groupby("district", as_index=False).sum(numeric_only=True)
        for (year, office), cols in contests.items():
            tot_col = cols["Total"]
            dem_col = cols["Dem"]
            rep_col = cols["Rep"]
            for _, r in g.iterrows():
                d = str(r["district"]).strip()
                sums_total[(year, office)][d] += float(r.get(tot_col, 0.0))
                sums_dem[(year, office)][d] += float(r.get(dem_col, 0.0))
                sums_rep[(year, office)][d] += float(r.get(rep_col, 0.0))

    written = 0
    for (year, office), _cols in sorted(contests.items()):
        contest_type = OFFICE_TO_CONTEST_TYPE[office]
        existing_path = out_dir / f"congressional_{contest_type}_{year}.json"
        dem_candidate, rep_candidate = infer_candidate_names(existing_path)

        dem_map = {d: int(round(v)) for d, v in sums_dem[(year, office)].items()}
        rep_map = {d: int(round(v)) for d, v in sums_rep[(year, office)].items()}
        total_map = {d: int(round(v)) for d, v in sums_total[(year, office)].items()}
        oth_map = {}
        for d, tot in total_map.items():
            oth = int(tot) - int(dem_map.get(d, 0)) - int(rep_map.get(d, 0))
            if oth < 0:
                oth = 0
            oth_map[d] = oth

        payload = build_payload(
            year=year,
            contest_type=contest_type,
            office_label=office,
            dem_candidate=dem_candidate,
            rep_candidate=rep_candidate,
            dem_map=dem_map,
            rep_map=rep_map,
            oth_map=oth_map,
            source="dra_blockfile_direct",
        )
        existing_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        written += 1
        print(f"Wrote {existing_path.name}")

    rebuild_manifest(out_dir)
    print(f"Done. Rebuilt {written} congressional slices and updated manifest.")


if __name__ == "__main__":
    main()

