"""Apply year-matched SBE precinct -> modern target display bridges to contest JSONs.

This is intentionally a display-layer postprocessor: district shatter artifacts keep
their election-vintage matching, while precinct contest rows are expanded/merged so
their keys can join to the configured modern OneMap display target.

For the December 2025 target basis, build the bridge first, then pass it here:

  python scripts/apply_sbe_vintage_onemap_bridge_to_contests.py \
    --year 2024 \
    --bridge-csv data/crosswalks/precinct_sbe_2024_to_onemap_2025_12_vap.csv \
    --sbe-shp data/census/SBE_PRECINCTS_20240723/SBE_PRECINCTS_20240723.shp \
    --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from build_district_contests_from_batch_shatter import (
    calculate_competitiveness,
    load_sbe_precinct_code_map,
)


ROOT = Path(__file__).resolve().parent.parent
MODERN_TARGET_PRECINCTS = ROOT / "data/census/SBE_PRECINCTS_20251212/SBE_PRECINCTS_20251212.shp"
MODERN_DISPLAY_GEOJSON = ROOT / "data/2025Voting_Precincts.geojson"

YEAR_CONFIG = {
    2020: {
        "bridge": ROOT / "data/crosswalks/precinct_sbe_2020_to_onemap_2025_12_vap.csv",
        "shp": ROOT / "data/census/SBE_PRECINCTS_20201018/SBE_PRECINCTS_20201018.shp",
    },
    2022: {
        "bridge": ROOT / "data/crosswalks/precinct_sbe_2022_to_onemap_2025_12_vap.csv",
        "shp": ROOT / "data/census/SBE_PRECINCTS_20220831/SBE_PRECINCTS_20220831.shp",
    },
    2024: {
        "bridge": ROOT / "data/crosswalks/precinct_sbe_2024_to_onemap_2025_12_vap.csv",
        "shp": ROOT / "data/census/SBE_PRECINCTS_20240723/SBE_PRECINCTS_20240723.shp",
    },
}


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def split_key(key: str) -> tuple[str, str]:
    value = norm(key)
    if " - " not in value:
        return value, ""
    county, precinct = value.split(" - ", 1)
    return norm(county), norm(precinct)


def is_non_geographic_precinct(precinct: str, county: str = "") -> bool:
    token = norm(precinct)
    county = norm(county)
    if not token:
        return True
    if county in {"CASWELL", "WAKE"} and token == "PROVI":
        return False
    if token == "PROVIDENCE":
        return False
    if token in {
        "EV",
        "ABS",
        "ABSEN",
        "ABSENTEE",
        "PROV",
        "PROVI",
        "PROVISIONAL",
        "PROVSIONAL",
        "CURBSIDE",
        "TRANSFER",
        "BOE",
    }:
        return True
    if token.startswith(("EV", "OS ", "OS-", "OS_", "OS")):
        return True
    if token.endswith(" EV") or " EV " in token or "-EV" in token or "_EV" in token:
        return True
    flags = [
        "ABSENTEE",
        "ABS-SUPPLEMENTAL",
        "ABSEN",
        "ABS BY-MAIL",
        "ADD ABS BY-MAIL",
        "PROVISIONAL",
        "PROVSIONAL",
        "PROVI",
        "TRANSFER",
        "CURBSIDE",
        "ONE STOP",
        "ONE-STOP",
        "ONESTOP",
        "MAIL ABSENTEE",
        "EARLY VOT",
        "VOTE CENTER",
        "VOTECENTER",
        "ELECTIONS ANNEX",
        "EARLYVOTE",
    ]
    if any(flag in token for flag in flags):
        return True
    if county == "HENDERSON" and token in {"CV", "CV CAROLINA VILLAGE", "CAROLINA VILLAGE"}:
        return True
    if county == "LEE" and token in {"LEE COUNTY BOE", "MCSWAIN CENTER"}:
        return True
    if county == "SURRY" and token in {"DBOS", "MAOS"}:
        return True
    if " BOE" in token or token.endswith(" BOE") or token.startswith("BOE "):
        return True
    return False


def allocate_integer_shares(total: int, weights: list[float]) -> list[int]:
    if total <= 0 or not weights:
        return [0 for _ in weights]
    weight_sum = sum(float(w or 0) for w in weights)
    if weight_sum <= 0:
        return [0 for _ in weights]
    raw = [total * (float(w or 0) / weight_sum) for w in weights]
    floors = [int(x // 1) for x in raw]
    remainder = int(total - sum(floors))
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def numeric_vote(value: object) -> int:
    try:
        return int(round(float(value or 0)))
    except Exception:
        return 0


def recalc_row(row: dict) -> dict:
    dem = numeric_vote(row.get("dem_votes"))
    rep = numeric_vote(row.get("rep_votes"))
    other = numeric_vote(row.get("other_votes"))
    total = dem + rep + other
    margin = rep - dem
    margin_pct = round((margin / total) * 100.0, 4) if total else 0.0
    winner = "REP" if rep > dem else ("DEM" if dem > rep else "TIE")
    return {
        **row,
        "dem_votes": dem,
        "rep_votes": rep,
        "other_votes": other,
        "total_votes": total,
        "margin": margin,
        "margin_pct": margin_pct,
        "winner": winner,
        "color": calculate_competitiveness(margin_pct),
    }


def code_variants(code: str) -> set[str]:
    token = norm(code)
    out = {token} if token else set()
    match = re.fullmatch(r"0*([0-9]{1,4})([A-Z]{0,2})", token)
    if match:
        number = int(match.group(1))
        suffix = match.group(2) or ""
        for width in range(1, 5):
            out.add(f"{str(number).zfill(width)}{suffix}")
    return {v for v in out if v}


def load_bridge_entries(bridge_path: Path, shp_path: Path) -> dict[str, list[dict[str, float | str]]]:
    bridge = pd.read_csv(bridge_path, dtype=str).fillna("")
    required = {"sbe_precinct_id", "onemap_precinct_id", "share"}
    if not required.issubset(set(bridge.columns)):
        raise ValueError(f"{bridge_path} missing required columns {sorted(required)}")

    entries: dict[str, list[dict[str, float | str]]] = defaultdict(list)
    for row in bridge.itertuples(index=False):
        source = norm(getattr(row, "sbe_precinct_id"))
        target = norm(getattr(row, "onemap_precinct_id"))
        try:
            share = float(getattr(row, "share") or 0)
        except Exception:
            share = 0.0
        if source and target and share > 0:
            entries[source].append({"target": target, "share": share})

    # Normalize shares by source key.
    for source, source_entries in list(entries.items()):
        total = sum(float(e["share"]) for e in source_entries)
        if total <= 0:
            del entries[source]
            continue
        for entry in source_entries:
            entry["share"] = float(entry["share"]) / total

    alias_to_source: dict[str, str] = {}
    sbe_name_map = load_sbe_precinct_code_map(shp_path)
    for (county, alias), code in sbe_name_map.items():
        source = f"{norm(county)} - {norm(code)}"
        alias_key = f"{norm(county)} - {norm(alias)}"
        if source in entries and alias_key != source:
            alias_to_source[alias_key] = source

    for source in list(entries):
        county, code = split_key(source)
        if not county or not code:
            continue
        for variant in code_variants(code):
            alias_key = f"{county} - {variant}"
            if alias_key != source:
                alias_to_source.setdefault(alias_key, source)

        # Wake-style SBE rows can use an alpha suffix where OneMap carries only the base code.
        if re.fullmatch(r"\d{2}-\d{2}", code):
            alias_to_source.setdefault(f"{county} - {code}A", source)

    for alias_key, source in alias_to_source.items():
        if alias_key not in entries and source in entries:
            entries[alias_key] = [dict(entry) for entry in entries[source]]

    return dict(entries)


def expand_row(row: dict, bridge_entries: dict[str, list[dict[str, float | str]]]) -> tuple[list[dict], bool]:
    key = norm(row.get("county"))
    county, precinct = split_key(key)
    if not county or not precinct or is_non_geographic_precinct(precinct, county):
        return [row], False

    entries = bridge_entries.get(key)
    if not entries:
        return [row], False

    targets = [str(entry["target"]) for entry in entries]
    weights = [float(entry["share"]) for entry in entries]
    if len(targets) == 1 and targets[0] == key:
        return [row], False

    dem_alloc = allocate_integer_shares(numeric_vote(row.get("dem_votes")), weights)
    rep_alloc = allocate_integer_shares(numeric_vote(row.get("rep_votes")), weights)
    other_alloc = allocate_integer_shares(numeric_vote(row.get("other_votes")), weights)
    expanded = []
    for idx, target in enumerate(targets):
        expanded.append(
            recalc_row(
                {
                    **row,
                    "county": target,
                    "dem_votes": dem_alloc[idx],
                    "rep_votes": rep_alloc[idx],
                    "other_votes": other_alloc[idx],
                }
            )
        )
    return expanded, True


def aggregate_rows(rows: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for row in rows:
        key = norm(row.get("county"))
        if key not in by_key:
            by_key[key] = recalc_row({**row, "county": key})
            continue
        existing = by_key[key]
        by_key[key] = recalc_row(
            {
                **existing,
                "county": key,
                "dem_votes": numeric_vote(existing.get("dem_votes")) + numeric_vote(row.get("dem_votes")),
                "rep_votes": numeric_vote(existing.get("rep_votes")) + numeric_vote(row.get("rep_votes")),
                "other_votes": numeric_vote(existing.get("other_votes")) + numeric_vote(row.get("other_votes")),
            }
        )
    return [by_key[key] for key in sorted(by_key)]


def relative_path(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def stamp_metadata(payload: dict, *, year: int, bridge_path: Path) -> bool:
    meta = payload.setdefault("meta", {})
    updates = {
        "source": f"sbe{year}_to_onemap2025_12_vap_bridge",
        "bridge": relative_path(bridge_path),
        "modern_target_precincts": relative_path(MODERN_TARGET_PRECINCTS),
        "display_geojson": relative_path(MODERN_DISPLAY_GEOJSON),
    }
    changed = False
    for key, value in updates.items():
        if meta.get(key) != value:
            meta[key] = value
            changed = True
    return changed


def bridge_already_applied(payload: dict, *, year: int, bridge_path: Path) -> bool:
    meta = payload.get("meta") or {}
    return (
        meta.get("source") == f"sbe{year}_to_onemap2025_12_vap_bridge"
        and meta.get("bridge") == relative_path(bridge_path)
    )


def apply_to_file(
    path: Path,
    bridge_entries: dict[str, list[dict[str, float | str]]],
    *,
    year: int,
    bridge_path: Path,
    dry_run: bool,
) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    already_applied = bridge_already_applied(payload, year=year, bridge_path=bridge_path)
    expanded: list[dict] = []
    touched: set[str] = set()
    if already_applied:
        expanded = rows
    else:
        for row in rows:
            next_rows, changed = expand_row(row, bridge_entries)
            if changed:
                touched.add(norm(row.get("county")))
            expanded.extend(next_rows)

    metadata_changed = stamp_metadata(payload, year=year, bridge_path=bridge_path)
    if not touched and not metadata_changed:
        return {"changed": False, "rows_before": len(rows), "rows_after": len(rows), "touched": []}

    if touched:
        payload["rows"] = aggregate_rows(expanded)
    if not dry_run:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "changed": True,
        "rows_before": len(rows),
        "rows_after": len(payload["rows"]),
        "touched": sorted(touched),
    }


def update_manifest(manifest_path: Path, summaries: dict[str, dict], dry_run: bool) -> None:
    if dry_run or not manifest_path.exists():
        return
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = payload.get("files") or []
    rows_by_file = {name: summary["rows_after"] for name, summary in summaries.items() if summary.get("changed")}
    if not rows_by_file:
        return
    for entry in files:
        file_name = str(entry.get("file") or "")
        if file_name in rows_by_file:
            entry["rows"] = int(rows_by_file[file_name])
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, choices=sorted(YEAR_CONFIG), required=True)
    parser.add_argument(
        "--bridge-csv",
        type=Path,
        default=None,
        help="Explicit SBE vintage -> modern target VAP bridge CSV. Defaults to the configured 2025 bridge for --year.",
    )
    parser.add_argument(
        "--sbe-shp",
        type=Path,
        default=None,
        help="Explicit year-matched SBE precinct shapefile for name/code aliases.",
    )
    parser.add_argument("--contests-dir", type=Path, default=ROOT / "data/contests")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/contests/manifest.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--only",
        nargs="*",
        default=[],
        help="Optional contest JSON file names to process.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = YEAR_CONFIG[int(args.year)]
    bridge_path = Path(args.bridge_csv) if args.bridge_csv is not None else Path(cfg["bridge"])
    shp_path = Path(args.sbe_shp) if args.sbe_shp is not None else Path(cfg["shp"])
    bridge_entries = load_bridge_entries(bridge_path, shp_path)
    requested = {Path(name).name for name in args.only}
    files = sorted(Path(args.contests_dir).glob(f"*_{int(args.year)}.json"))
    if requested:
        files = [path for path in files if path.name in requested]

    summaries: dict[str, dict] = {}
    for path in files:
        result = apply_to_file(
            path,
            bridge_entries,
            year=int(args.year),
            bridge_path=bridge_path,
            dry_run=bool(args.dry_run),
        )
        if result.get("changed"):
            summaries[path.name] = result

    update_manifest(Path(args.manifest), summaries, dry_run=bool(args.dry_run))
    print(
        json.dumps(
            {
                "year": int(args.year),
                "dry_run": bool(args.dry_run),
                "bridge_csv": bridge_path.as_posix(),
                "sbe_shp": shp_path.as_posix(),
                "bridge_keys": len(bridge_entries),
                "changed_files": summaries,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
