#!/usr/bin/env python3
"""
Salvage 2008 NCSBE name-only precincts onto modern NCOneMap keys.

2008 results_pct drops precinct_abbrv and exports display names only
(e.g. "GWALTNEY #1"). VTD00 still has both code + name for that era, and
modern Voting_Precincts often merges those units (G1+G2 -> G1G2).

Pipeline:
  1) Match 2008 precinct name -> VTD00 NAME00 / VTDST00 (within county)
  2) Map VTD00 code -> modern precinct via spatial best-match crosswalk
  3) Emit override rows: year,raw_precinct_key,canonical_precinct_key

Does not rewrite the 2008 election CSV; feeds existing resolve/shatter via
data/mappings/precinct_key_overrides.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

from build_district_results_2024_lines import (  # noqa: E402
    NC_COUNTY_FIPS,
    _compact,
    _norm,
)


def _norm_name(text: str) -> str:
    t = _norm(text)
    t = t.replace("#", " ")
    t = t.replace("_", " ").replace("-", " ").replace(".", " ")
    t = re.sub(r"\bPRECINCT\b", " ", t)
    t = " ".join(t.split())
    return t


def _name_keys(text: str) -> set[str]:
    n = _norm_name(text)
    out = {n, _compact(n)}
    # DROP leading code tokens like "G1 GWALTNEY 1" if present in other years.
    parts = n.split()
    if parts and re.fullmatch(r"[A-Z]*\d+[A-Z]*", parts[0]) and len(parts) > 1:
        rest = " ".join(parts[1:])
        out.add(rest)
        out.add(_compact(rest))
    return {x for x in out if x}


def load_vtd00_index(vtd_path: Path) -> dict[str, list[dict[str, str]]]:
    geo = json.load(open(vtd_path, "r", encoding="utf-8"))
    by_county: dict[str, list[dict[str, str]]] = defaultdict(list)
    for f in geo.get("features", []):
        props = f.get("properties") or {}
        fp = str(props.get("COUNTYFP00", "")).zfill(3)
        county = NC_COUNTY_FIPS.get(fp, "")
        code = _norm(props.get("VTDST00", ""))
        name = _norm_name(props.get("NAME00", ""))
        if not county or not code:
            continue
        by_county[county].append(
            {
                "code": code,
                "name": name,
                "vtd_key": f"{county} - {code}",
            }
        )
    return by_county


def load_best_old_to_new(path: Path, min_old_share: float) -> dict[str, tuple[str, float]]:
    df = pd.read_csv(path, dtype=str)
    out: dict[str, tuple[str, float]] = {}
    for _, r in df.iterrows():
        old_key = _norm(r.get("old_precinct_key", ""))
        new_key = _norm(r.get("new_precinct_key", ""))
        share = float(pd.to_numeric(r.get("old_share"), errors="coerce") or 0.0)
        if not old_key or not new_key:
            continue
        if share < min_old_share:
            continue
        prev = out.get(old_key)
        if prev is None or share > prev[1]:
            out[old_key] = (new_key, share)
    return out


def load_modern_precinct_keys(voting_geojson: Path) -> set[str]:
    geo = json.load(open(voting_geojson, "r", encoding="utf-8"))
    keys: set[str] = set()
    for f in geo.get("features", []):
        props = f.get("properties") or {}
        county = _norm(props.get("county_nam", ""))
        prec = _norm(props.get("prec_id", ""))
        if county and prec:
            keys.add(f"{county} - {prec}")
    return keys


def load_2008_precinct_keys(results_csv: Path) -> set[str]:
    keys: set[str] = set()
    with open(results_csv, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            county = _norm(row.get("county", ""))
            precinct = _norm(row.get("precinct", ""))
            if not county or not precinct:
                continue
            # skip obvious non-geo buckets
            p = _norm_name(precinct)
            if p in {
                "ONE STOP",
                "ABSENTEE BY MAIL",
                "PROVISIONAL",
                "TRANSFER",
                "ABSENTEE",
                "PROV",
                "CURBSIDE",
                "TRANSERS",
            }:
                continue
            if "ABSENTEE" in p or "ONE STOP" in p or p.startswith("OS ") or "CURBSIDE" in p:
                continue
            keys.add(f"{county} - {precinct}")
    return keys


def _code_candidates(precinct: str) -> list[str]:
    """Extract likely era precinct/VTD codes from messy 2008 labels."""
    p = _norm(precinct)
    out: list[str] = []

    def add(x: str) -> None:
        x = _norm(x)
        if x and x not in out:
            out.append(x)

    add(p)

    # "0053 - SILVER CREEK 03" / "EUR - EUREKA" / "01 - BROGDEN ..."
    m = re.match(r"^([A-Z0-9][A-Z0-9.\-]{0,11})\s+-\s+(.+)$", p)
    if m:
        add(m.group(1))
        add(m.group(2))

    # "PCT 1" / "PCT 10"
    m = re.match(r"^PCT\s+#?\s*([0-9]{1,3}[A-Z]?)$", p)
    if m:
        n = m.group(1)
        add(n)
        if n.isdigit():
            add(str(int(n)))
            add(f"{int(n):02d}")
            add(f"{int(n):03d}")

    # "PRECINCT 01-07" / "PRECINCT 01-07A"
    m = re.search(r"\bPRECINCT\s+(\d{2}-\d{2}[A-Z]?)\b", p)
    if m:
        add(m.group(1))
        add(m.group(1).rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))

    # "01.1 - ..." Buncombe-style
    m = re.match(r"^(\d{1,2}\.\d)\b", p)
    if m:
        add(m.group(1))

    # "1-A ELIZABETH CITY" / "P02A" / "G41"
    m = re.match(r"^([A-Z]?\d{1,3}[A-Z]?)\b", p)
    if m:
        add(m.group(1))

    # trailing " #86" / " #04"
    m = re.search(r"#\s*([0-9]{1,3}[A-Z]?)\s*$", p)
    if m:
        add(m.group(1))
        if m.group(1).isdigit():
            add(str(int(m.group(1))))
            add(f"{int(m.group(1)):02d}")

    # "NO 1" / "NUMBER 10"
    m = re.search(r"\b(?:NO|NUMBER|NUM)\s*([0-9]{1,3})\b", p)
    if m:
        add(m.group(1))
        add(f"{int(m.group(1)):02d}")

    return out


def match_name_to_vtd(
    county: str,
    precinct: str,
    vtd_by_county: dict[str, list[dict[str, str]]],
) -> tuple[str | None, str]:
    entries = vtd_by_county.get(county, [])
    if not entries:
        return None, "no_county_vtd"
    keys = _name_keys(precinct)
    hits = []
    for e in entries:
        ekeys = _name_keys(e["name"]) | {_norm(e["code"]), _compact(e["code"])}
        if keys & ekeys:
            hits.append(e)
    # unique code hit only
    if len(hits) == 1:
        return hits[0]["vtd_key"], "unique_name"
    if len(hits) > 1:
        codes = {h["code"] for h in hits}
        if len(codes) == 1:
            return hits[0]["vtd_key"], "unique_code_multi_name"
        return None, "ambiguous_vtd_name"

    # Second pass: extract embedded codes and match VTDST00 uniquely.
    code_index: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        code_index[_norm(e["code"])].add(e["vtd_key"])
        code_index[_compact(e["code"])].add(e["vtd_key"])
        if e["code"].isdigit():
            code_index[str(int(e["code"]))].add(e["vtd_key"])
            code_index[f"{int(e['code']):02d}"].add(e["vtd_key"])
            code_index[f"{int(e['code']):03d}"].add(e["vtd_key"])
            code_index[f"{int(e['code']):04d}"].add(e["vtd_key"])

    code_hits: set[str] = set()
    for cand in _code_candidates(precinct):
        code_hits |= code_index.get(_norm(cand), set())
        code_hits |= code_index.get(_compact(cand), set())
    if len(code_hits) == 1:
        return next(iter(code_hits)), "unique_extracted_code"
    if len(code_hits) > 1:
        return None, "ambiguous_extracted_code"
    return None, "unmatched_vtd_name"


def main() -> None:
    ap = argparse.ArgumentParser(description="Suggest 2008 overrides via VTD00 -> modern crosswalk.")
    ap.add_argument(
        "--results-csv",
        type=Path,
        default=Path("data/2008/20081104__nc__general__precinct.csv"),
    )
    ap.add_argument(
        "--vtd00",
        type=Path,
        default=Path("data/census/tl_2008_37_vtd00_merged.geojson"),
    )
    ap.add_argument(
        "--vtd-crosswalk",
        type=Path,
        default=Path("data/crosswalks/vtd00_to_nconemap_best_old_to_new.csv"),
    )
    ap.add_argument(
        "--voting-geojson",
        type=Path,
        default=Path("data/Voting_Precincts.geojson"),
    )
    ap.add_argument("--min-old-share", type=float, default=0.85)
    ap.add_argument(
        "--out-suggestions",
        type=Path,
        default=Path("data/reports/precinct_key_overrides_2008_vtd00_suggestions.csv"),
    )
    ap.add_argument(
        "--out-overrides",
        type=Path,
        default=Path("data/reports/precinct_key_overrides_2008_vtd00_auto.csv"),
    )
    ap.add_argument(
        "--apply-to-overrides",
        action="store_true",
        help="Append high-confidence rows into data/mappings/precinct_key_overrides.csv",
    )
    args = ap.parse_args()

    results_csv = args.results_csv if args.results_csv.is_absolute() else ROOT / args.results_csv
    vtd00 = args.vtd00 if args.vtd00.is_absolute() else ROOT / args.vtd00
    xw = args.vtd_crosswalk if args.vtd_crosswalk.is_absolute() else ROOT / args.vtd_crosswalk
    voting = args.voting_geojson if args.voting_geojson.is_absolute() else ROOT / args.voting_geojson
    out_sug = args.out_suggestions if args.out_suggestions.is_absolute() else ROOT / args.out_suggestions
    out_auto = args.out_overrides if args.out_overrides.is_absolute() else ROOT / args.out_overrides

    if not xw.exists():
        raise SystemExit(
            f"Missing VTD crosswalk: {xw}\n"
            "Run: python scripts/build_vtd_to_modern_precinct_crosswalk.py"
        )

    vtd_by_county = load_vtd00_index(vtd00)
    best = load_best_old_to_new(xw, args.min_old_share)
    modern_keys = load_modern_precinct_keys(voting)
    raw_keys = load_2008_precinct_keys(results_csv)

    suggestions: list[dict[str, str]] = []
    auto_rows: list[dict[str, str]] = []
    stats = defaultdict(int)

    for raw_key in sorted(raw_keys):
        stats["total"] += 1
        county, precinct = raw_key.split(" - ", 1)
        vtd_key, vtd_status = match_name_to_vtd(county, precinct, vtd_by_county)
        stats[f"vtd_{vtd_status}"] += 1
        if not vtd_key:
            suggestions.append(
                {
                    "year": "2008",
                    "raw_precinct_key": raw_key,
                    "vtd00_key": "",
                    "canonical_precinct_key": "",
                    "old_share": "",
                    "status": vtd_status,
                }
            )
            continue

        mapped = best.get(vtd_key)
        if not mapped:
            stats["no_crosswalk_hit"] += 1
            suggestions.append(
                {
                    "year": "2008",
                    "raw_precinct_key": raw_key,
                    "vtd00_key": vtd_key,
                    "canonical_precinct_key": "",
                    "old_share": "",
                    "status": "no_crosswalk_hit",
                }
            )
            continue

        canonical, share = mapped
        if canonical not in modern_keys:
            stats["canonical_missing_modern"] += 1
            status = "canonical_missing_modern"
        else:
            status = "auto_accept" if share >= args.min_old_share else "review_low_share"
            if status == "auto_accept":
                stats["auto_accept"] += 1
                auto_rows.append(
                    {
                        "year": "2008",
                        "raw_precinct_key": raw_key,
                        "canonical_precinct_key": canonical,
                    }
                )
            else:
                stats["review_low_share"] += 1

        suggestions.append(
            {
                "year": "2008",
                "raw_precinct_key": raw_key,
                "vtd00_key": vtd_key,
                "canonical_precinct_key": canonical,
                "old_share": f"{share:.6f}",
                "status": status,
            }
        )

    out_sug.parent.mkdir(parents=True, exist_ok=True)
    with open(out_sug, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "year",
                "raw_precinct_key",
                "vtd00_key",
                "canonical_precinct_key",
                "old_share",
                "status",
            ],
        )
        w.writeheader()
        w.writerows(suggestions)

    with open(out_auto, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["year", "raw_precinct_key", "canonical_precinct_key"])
        w.writeheader()
        w.writerows(auto_rows)

    if args.apply_to_overrides:
        overrides_path = ROOT / "data" / "mappings" / "precinct_key_overrides.csv"
        existing = set()
        rows_out: list[dict[str, str]] = []
        if overrides_path.exists():
            with open(overrides_path, "r", encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    year = _norm(r.get("year", ""))
                    raw = _norm(r.get("raw_precinct_key", ""))
                    can = _norm(r.get("canonical_precinct_key", ""))
                    if not raw or not can:
                        continue
                    existing.add((year, raw))
                    rows_out.append(
                        {"year": year if year else "*", "raw_precinct_key": raw, "canonical_precinct_key": can}
                    )
        added = 0
        for r in auto_rows:
            key = (_norm(r["year"]), _norm(r["raw_precinct_key"]))
            if key in existing:
                continue
            rows_out.append(r)
            existing.add(key)
            added += 1
        with open(overrides_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["year", "raw_precinct_key", "canonical_precinct_key"])
            w.writeheader()
            w.writerows(rows_out)
        stats["overrides_added"] = added
        print(f"Appended {added} rows to {overrides_path}")

    print(f"Wrote {out_sug}")
    print(f"Wrote {out_auto} ({len(auto_rows)} auto-accept rows)")
    print(json.dumps(dict(stats), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
