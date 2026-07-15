#!/usr/bin/env python3
"""Audit early urban-county SBE2006 -> OneMap precinct apportionment.

The frontend renders pre-2016 precinct contests on modern precinct polygons by
splitting SBE2006 source rows through `sbe2006_to_onemap_precinct_weights.json`.
This diagnostic mirrors that bridge and compares the old last-row-wins behavior
with additive apportionment for dense urban counties.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS = ROOT / "data" / "mappings" / "sbe2006_to_onemap_precinct_weights.json"
DEFAULT_MODERN_GEOJSON = ROOT / "data" / "2025Voting_Precincts.geojson"
DEFAULT_DETAIL_CSV = ROOT / "data" / "reports" / "sbe2006_urban_precinct_bridge_audit.csv"
DEFAULT_SUMMARY_JSON = ROOT / "data" / "reports" / "sbe2006_urban_precinct_bridge_summary.json"

URBAN_COUNTIES = {
    "BUNCOMBE",
    "CABARRUS",
    "CUMBERLAND",
    "DURHAM",
    "FORSYTH",
    "GASTON",
    "GUILFORD",
    "MECKLENBURG",
    "NEW HANOVER",
    "UNION",
    "WAKE",
}

COMMON_PRECINCT_WORDS = ("PRECINCT", "PCT", "WARD", "DISTRICT", "TOWNSHIP", "BOX", "VOTING", "LOCATION")


def normalize_token(value: object) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[^A-Z0-9 ._-]+", " ", text)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_alias(value: object) -> str:
    text = normalize_token(value)
    for word in COMMON_PRECINCT_WORDS:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
    text = text.replace("-", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", normalize_token(value))


def split_precinct_key(value: object) -> tuple[str, str]:
    text = normalize_token(value)
    if " - " not in text:
        return "", text
    county, precinct = text.split(" - ", 1)
    return normalize_token(county), normalize_token(precinct)


def extract_precinct_alias_candidates(raw_value: object) -> set[str]:
    """Mirror the relevant frontend alias candidates closely enough for audits."""
    aliases: set[str] = set()
    raw = normalize_token(raw_value)
    if not raw:
        return aliases

    if raw:
        aliases.add(raw)
    county, local = split_precinct_key(raw)
    if county and local:
        aliases.add(local)

    for token in (raw, local):
        if not token:
            continue
        alias = normalize_alias(token)
        packed = compact(token)
        if alias:
            aliases.add(alias)
            alias_packed = compact(alias)
            if alias_packed:
                aliases.add(alias_packed)
        if packed:
            aliases.add(packed)

        no_hash = re.sub(r"#\s*\d+\b", " ", token)
        no_hash = re.sub(r"\s+", " ", no_hash).strip()
        if no_hash and no_hash != token:
            aliases.add(no_hash)
            aliases.add(normalize_alias(no_hash))
            aliases.add(compact(no_hash))

        if "/" in token:
            for part in token.split("/"):
                part = normalize_token(part)
                if part:
                    aliases.add(part)
                    aliases.add(compact(part))

        if "_" in token:
            for part in token.split("_"):
                part = normalize_token(part)
                if part:
                    aliases.add(part)
                    aliases.add(compact(part))

        group_suffix_stripped = re.sub(r"[-\s]+G\d+[A-Z]?\b$", " ", token)
        group_suffix_stripped = re.sub(r"\s+", " ", group_suffix_stripped).strip()
        if group_suffix_stripped and group_suffix_stripped != token and re.search(r"[A-Z]", group_suffix_stripped):
            aliases.add(group_suffix_stripped)
            group_suffix_alias = normalize_alias(group_suffix_stripped)
            if group_suffix_alias:
                aliases.add(group_suffix_alias)
                aliases.add(compact(group_suffix_alias))
            aliases.add(compact(group_suffix_stripped))

        parts = [p for p in normalize_alias(token).split(" ") if p]
        if parts and re.search(r"\d", parts[0]):
            aliases.add(parts[0])
            rest = " ".join(parts[1:]).strip()
            if rest:
                aliases.add(rest)
                aliases.add(compact(rest))

        if len(parts) >= 2 and len(parts) % 2 == 0:
            midpoint = len(parts) // 2
            if parts[:midpoint] == parts[midpoint:]:
                collapsed = " ".join(parts[:midpoint]).strip()
                collapsed_hyphen = collapsed.replace(" ", "-")
                aliases.add(collapsed)
                aliases.add(collapsed_hyphen)
                aliases.add(compact(collapsed))

        if re.fullmatch(r"\d+", token):
            aliases.add(str(int(token)))
            aliases.add(token.zfill(4))

    return {a for a in aliases if a}


def load_weight_index(path: Path) -> dict[str, dict[str, list[dict[str, float | str]]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, list[dict[str, float | str]]]] = {}
    for county_raw, alias_obj in (payload.get("counties") or {}).items():
        county = normalize_token(county_raw)
        if not county or not isinstance(alias_obj, dict):
            continue
        county_map: dict[str, list[dict[str, float | str]]] = {}
        for alias_raw, entries_raw in alias_obj.items():
            alias = normalize_token(alias_raw)
            if not alias or not isinstance(entries_raw, list):
                continue
            entries: list[dict[str, float | str]] = []
            for entry in entries_raw:
                if not isinstance(entry, dict):
                    continue
                code = normalize_token(entry.get("code"))
                try:
                    weight = float(entry.get("weight"))
                except (TypeError, ValueError):
                    continue
                if code and math.isfinite(weight) and weight > 0:
                    entries.append({"code": code, "weight": weight})
            if entries:
                county_map[alias] = entries
        if county_map:
            out[county] = county_map
    return out


def load_modern_precinct_codes(path: Path) -> dict[str, set[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = defaultdict(set)
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        county = normalize_token(props.get("county_nam") or props.get("COUNTYNAME") or props.get("County"))
        code = normalize_token(props.get("prec_id") or props.get("PREC_ID") or props.get("precinct"))
        if county and code:
            out[county].add(code)
    return dict(out)


def bridge_entries(
    weights_by_county: dict[str, dict[str, list[dict[str, float | str]]]],
    county: str,
    precinct: str,
) -> list[dict[str, float | str]]:
    county_map = weights_by_county.get(county)
    if not county_map:
        return []

    by_code: dict[str, float] = defaultdict(float)
    for alias in extract_precinct_alias_candidates(precinct) | extract_precinct_alias_candidates(f"{county} - {precinct}"):
        for entry in county_map.get(normalize_token(alias), []):
            code = normalize_token(entry.get("code"))
            weight = float(entry.get("weight") or 0)
            if code and math.isfinite(weight) and weight > 0:
                by_code[code] += weight

    total = sum(by_code.values())
    if total <= 0:
        return []
    return [
        {"code": code, "weight": weight / total}
        for code, weight in sorted(by_code.items(), key=lambda item: (-item[1], item[0]))
    ]


def signed_margin_pct(dem: float, rep: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return ((rep - dem) / total) * 100.0


def winner(dem: float, rep: float, total: float) -> str:
    if total <= 0:
        return "TIE"
    if rep > dem:
        return "REP"
    if dem > rep:
        return "DEM"
    return "TIE"


def extract_president_precinct_code(precinct_raw: object, year: int) -> str:
    precinct = str(precinct_raw or "").strip()
    if not precinct:
        return ""
    upper = precinct.upper()
    if (
        "ABSENTEE" in upper
        or "PROVISIONAL" in upper
        or "ONE STOP" in upper
        or "CURBSIDE" in upper
        or upper.startswith("OS ")
        or upper.startswith("OS-")
    ):
        return upper
    if year >= 2008:
        return upper
    return re.split(r"[_\s]+", upper, maxsplit=1)[0].strip()


def load_president_rows_from_open_elections(path: Path) -> tuple[int, str, list[dict[str, Any]]]:
    year_match = re.search(r"(20\d{2})", path.name)
    year = int(year_match.group(1)) if year_match else 0
    by_precinct: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            office = str(row.get("office") or "").upper()
            if "PRESIDENT" not in office:
                continue
            county = normalize_token(row.get("county"))
            code = extract_president_precinct_code(row.get("precinct"), year)
            if not county or not code:
                continue
            key = f"{county} - {code}".replace("  ", " ").strip()
            party = str(row.get("party") or "").strip().upper()
            candidate = str(row.get("candidate") or "").strip()
            try:
                votes = float(row.get("votes") or 0)
            except (TypeError, ValueError):
                votes = 0.0

            node = by_precinct.setdefault(
                key,
                {"year": year, "county": key, "dem_votes": 0.0, "rep_votes": 0.0, "other_votes": 0.0, "dem_candidate": "", "rep_candidate": ""},
            )
            if party == "DEM":
                node["dem_votes"] += votes
                if not node["dem_candidate"] and candidate:
                    node["dem_candidate"] = candidate
            elif party == "REP":
                node["rep_votes"] += votes
                if not node["rep_candidate"] and candidate:
                    node["rep_candidate"] = candidate
            else:
                node["other_votes"] += votes

    rows = []
    for node in by_precinct.values():
        dem = float(node["dem_votes"])
        rep = float(node["rep_votes"])
        other = float(node["other_votes"])
        total = dem + rep + other
        node["total_votes"] = total
        node["margin"] = rep - dem
        node["margin_pct"] = signed_margin_pct(dem, rep, total)
        node["winner"] = winner(dem, rep, total)
        rows.append(node)
    rows.sort(key=lambda item: str(item["county"]))
    return year, "president", rows


def load_contest_rows(path: Path) -> tuple[int, str, list[dict[str, Any]]]:
    if path.suffix.lower() == ".csv":
        return load_president_rows_from_open_elections(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    year = int(payload.get("year") or 0)
    contest_type = str(payload.get("contest_type") or path.stem.rsplit("_", 1)[0])
    return year, contest_type, rows


def contest_paths(paths: list[str]) -> list[Path]:
    if paths:
        return [ROOT / p if not Path(p).is_absolute() else Path(p) for p in paths]

    defaults = []
    for year, filename in (
        (2000, "20001107__nc__general__precinct.csv"),
        (2004, "20041102__nc__general__precinct.csv"),
        (2008, "20081104__nc__general__precinct.csv"),
    ):
        path = ROOT / "data" / str(year) / filename
        if path.exists():
            defaults.append(path)
    for year in (2000, 2004, 2008):
        path = ROOT / "data" / "contests" / f"governor_{year}.json"
        if path.exists():
            defaults.append(path)
    return defaults


def audit_contest(
    contest_path: Path,
    weights_by_county: dict[str, dict[str, list[dict[str, float | str]]]],
    modern_codes_by_county: dict[str, set[str]],
    counties: set[str],
    min_margin_delta: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    year, contest_type, rows = load_contest_rows(contest_path)

    stats_by_county: dict[str, Counter[str]] = defaultdict(Counter)
    duplicate_source_keys: Counter[str] = Counter()
    targets_accum: dict[tuple[str, str], dict[str, Any]] = {}
    targets_overwrite: dict[tuple[str, str], dict[str, Any]] = {}
    low_max_weight_examples: list[dict[str, Any]] = []

    for row in rows:
        row_name = normalize_token(row.get("county"))
        county, precinct = split_precinct_key(row_name)
        if county not in counties or not precinct:
            continue
        duplicate_source_keys[row_name] += 1

        try:
            dem = float(row.get("dem_votes") or 0)
            rep = float(row.get("rep_votes") or 0)
            other = float(row.get("other_votes") or 0)
            total = float(row.get("total_votes") or (dem + rep + other))
        except (TypeError, ValueError):
            continue

        stats = stats_by_county[county]
        stats["rows"] += 1
        entries = bridge_entries(weights_by_county, county, precinct)
        if not entries:
            if precinct in modern_codes_by_county.get(county, set()):
                stats["direct_modern_match"] += 1
            else:
                stats["unmatched"] += 1
            continue

        stats["matched"] += 1
        if len(entries) > 1:
            stats["split_sources"] += 1
        max_weight = max(float(entry["weight"]) for entry in entries)
        if max_weight < 0.7:
            stats["low_max_weight"] += 1
            if len(low_max_weight_examples) < 40:
                low_max_weight_examples.append(
                    {
                        "county": county,
                        "source": row_name,
                        "max_weight": round(max_weight, 4),
                        "targets": ";".join(f"{entry['code']}:{float(entry['weight']):.3f}" for entry in entries[:8]),
                    }
                )

        for entry in entries:
            code = str(entry["code"])
            weight = float(entry["weight"])
            key = (county, code)
            apportioned = {
                "dem": dem * weight,
                "rep": rep * weight,
                "other": other * weight,
                "total": total * weight,
                "source": row_name,
                "weight": weight,
            }

            current = targets_accum.setdefault(
                key,
                {"dem": 0.0, "rep": 0.0, "other": 0.0, "total": 0.0, "sources": []},
            )
            current["dem"] += apportioned["dem"]
            current["rep"] += apportioned["rep"]
            current["other"] += apportioned["other"]
            current["total"] += apportioned["total"]
            current["sources"].append(apportioned)

            # This mirrors the frontend bug fixed in index.html: later source row wins.
            targets_overwrite[key] = apportioned

    details: list[dict[str, Any]] = []
    for key, accum in targets_accum.items():
        sources = accum["sources"]
        if len(sources) <= 1:
            continue
        overwrite = targets_overwrite[key]
        acc_margin = signed_margin_pct(accum["dem"], accum["rep"], accum["total"])
        old_margin = signed_margin_pct(overwrite["dem"], overwrite["rep"], overwrite["total"])
        acc_winner = winner(accum["dem"], accum["rep"], accum["total"])
        old_winner = winner(overwrite["dem"], overwrite["rep"], overwrite["total"])
        margin_delta = abs(acc_margin - old_margin)
        flag = old_winner != acc_winner or margin_delta >= min_margin_delta
        if not flag:
            continue
        county, target_code = key
        stats_by_county[county]["flagged_multi_source_targets"] += 1
        source_labels = [
            f"{s['source']}@{float(s['weight']):.3f}"
            for s in sorted(sources, key=lambda item: -float(item["total"]))[:6]
        ]
        details.append(
            {
                "contest_file": contest_path.relative_to(ROOT).as_posix(),
                "year": year,
                "contest_type": contest_type,
                "county": county,
                "target_precinct": f"{county} - {target_code}",
                "source_count": len(sources),
                "accumulated_total_votes": round(accum["total"], 3),
                "overwrite_source": overwrite["source"],
                "overwrite_winner": old_winner,
                "accumulated_winner": acc_winner,
                "overwrite_margin_pct": round(old_margin, 3),
                "accumulated_margin_pct": round(acc_margin, 3),
                "margin_delta_pct": round(margin_delta, 3),
                "sources": "; ".join(source_labels),
            }
        )

    summary = {
        "contest_file": contest_path.relative_to(ROOT).as_posix(),
        "year": year,
        "contest_type": contest_type,
        "counties": {},
        "duplicate_source_keys": [
            {"source": source, "count": count}
            for source, count in duplicate_source_keys.items()
            if count > 1
        ][:50],
        "low_max_weight_examples": low_max_weight_examples,
    }
    for county in sorted(counties):
        stats = stats_by_county[county]
        if not stats:
            continue
        rows_count = stats["rows"]
        matched = stats["matched"]
        summary["counties"][county] = {
            "rows": rows_count,
            "matched": matched,
            "direct_modern_match": stats["direct_modern_match"],
            "unmatched": stats["unmatched"],
            "match_pct": round((matched / rows_count) * 100.0, 2) if rows_count else 0.0,
            "direct_modern_match_pct": round((stats["direct_modern_match"] / rows_count) * 100.0, 2) if rows_count else 0.0,
            "unmatched_pct": round((stats["unmatched"] / rows_count) * 100.0, 2) if rows_count else 0.0,
            "split_sources": stats["split_sources"],
            "low_max_weight": stats["low_max_weight"],
            "flagged_multi_source_targets": stats["flagged_multi_source_targets"],
        }
    return details, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights-json", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--modern-geojson", type=Path, default=DEFAULT_MODERN_GEOJSON)
    parser.add_argument("--contest-json", action="append", default=[], help="Contest JSON to audit; defaults to available early president/governor contests.")
    parser.add_argument("--county", action="append", default=[], help="County to audit; defaults to major urban counties.")
    parser.add_argument("--min-margin-delta", type=float, default=15.0)
    parser.add_argument("--out-csv", type=Path, default=DEFAULT_DETAIL_CSV)
    parser.add_argument("--out-summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    args = parser.parse_args()

    counties = {normalize_token(c) for c in args.county if normalize_token(c)} or URBAN_COUNTIES
    weights_path = args.weights_json if args.weights_json.is_absolute() else ROOT / args.weights_json
    weights = load_weight_index(weights_path)
    modern_path = args.modern_geojson if args.modern_geojson.is_absolute() else ROOT / args.modern_geojson
    modern_codes = load_modern_precinct_codes(modern_path)
    paths = contest_paths(args.contest_json)
    if not paths:
        raise SystemExit("No contest JSON files found to audit.")

    all_details: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for path in paths:
        details, summary = audit_contest(path, weights, modern_codes, counties, args.min_margin_delta)
        all_details.extend(details)
        summaries.append(summary)

    all_details.sort(key=lambda row: (-float(row["margin_delta_pct"]), row["contest_file"], row["county"], row["target_precinct"]))

    out_csv = args.out_csv if args.out_csv.is_absolute() else ROOT / args.out_csv
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "contest_file",
        "year",
        "contest_type",
        "county",
        "target_precinct",
        "source_count",
        "accumulated_total_votes",
        "overwrite_source",
        "overwrite_winner",
        "accumulated_winner",
        "overwrite_margin_pct",
        "accumulated_margin_pct",
        "margin_delta_pct",
        "sources",
    ]
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_details)

    out_summary = args.out_summary_json if args.out_summary_json.is_absolute() else ROOT / args.out_summary_json
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "weights_json": weights_path.relative_to(ROOT).as_posix(),
        "modern_geojson": modern_path.relative_to(ROOT).as_posix(),
        "counties": sorted(counties),
        "min_margin_delta": args.min_margin_delta,
        "flagged_rows": len(all_details),
        "summaries": summaries,
    }
    out_summary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Wrote {out_csv.relative_to(ROOT)} ({len(all_details):,} flagged target precincts)")
    print(f"Wrote {out_summary.relative_to(ROOT)} ({len(summaries):,} contest summaries)")


if __name__ == "__main__":
    main()
