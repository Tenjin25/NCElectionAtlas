#!/usr/bin/env python3
"""Classify 2008 SBE2006 leftover precinct keys.

This audit is intentionally stdlib-only so it can run even when the local
geospatial Python stack is unavailable. It reads the SBE2006 DBF attributes
directly and classifies leftover OpenElections keys as non-geographic buckets,
exact SBE2006 geography, or resolvable SBE2006 split/alias rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import struct
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEFTOVERS = ROOT / "data" / "reports" / "precinct_key_overrides_2008_sbe2006_leftovers.csv"
DEFAULT_SBE2006_DBF = ROOT / "data" / "Precincts2006Gen" / "Precincts2006Gen.dbf"
DEFAULT_SMOKE_DIR = ROOT / "data" / "district_contests_agg_dec2025_smoke_2008"
DEFAULT_DETAIL = ROOT / "data" / "reports" / "precinct_key_overrides_2008_sbe2006_leftovers_classified.csv"
DEFAULT_SUMMARY = ROOT / "data" / "reports" / "precinct_key_overrides_2008_sbe2006_leftovers_classified_summary.json"


NON_GEO_FLAGS = (
    "ABSENTEE",
    "ABSEN",
    "ABS",
    "ONE STOP",
    "ONE-STOP",
    "EARLY",
    "EV ",
    "EV-",
    "EV_",
    "PROVISIONAL",
    "PROVI",
    "PROV",
    "CURBSIDE",
    "MAIL",
    "TRANSFER",
)


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def norm_name(value: object) -> str:
    text = norm(value).replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\bNO\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", norm(value))


def split_key(value: object) -> tuple[str, str]:
    text = norm(value)
    if " - " not in text:
        return "", text
    county, precinct = text.split(" - ", 1)
    return norm(county), norm(precinct)


def non_geo_category(precinct: object, county: object = "") -> str | None:
    t = norm(precinct)
    c = norm(county)
    if not t:
        return "unknown_bucket"
    if t == "PROVIDENCE":
        return None
    if c in {"CASWELL", "WAKE"} and t == "PROVI":
        return None
    if "CURBSIDE" in t or "CURB" in t:
        return "curbside"
    if t.startswith("TRANS ") or t.startswith("TRANS_") or re.match(r"^TRANS\d", t) or "TRANSFER" in t:
        return "transfer"
    if "PROVISIONAL" in t or "PROVI" in t or re.search(r"(^|[^A-Z0-9])PROV([^A-Z0-9]|$)", t):
        return "provisional"
    if (
        "ONE STOP" in t
        or "ONE-STOP" in t
        or t == "OS"
        or t.startswith("OS ")
        or t.startswith("OS-")
        or t.startswith("OS_")
        or re.match(r"^OS[A-Z0-9]+", t)
        or re.search(r"(^|[^A-Z0-9])OS([^A-Z0-9]|$)", t)
        or t == "ONESTOP"
        or t.startswith("ONESTOP ")
    ):
        return "one_stop"
    if "EARLY" in t or t == "EV" or re.match(r"^EV[A-Z0-9]+$", t):
        return "early"
    if "ABSENTEE" in t or "ABSEN" in t or t.startswith("ABS") or re.search(r"(^|[^A-Z0-9])ABS([^A-Z0-9]|$)", t):
        return "absentee"
    if "MAIL" in t:
        return "mail"
    if any(flag in t for flag in NON_GEO_FLAGS):
        return "unknown_bucket"
    if t in {"FAILSAFE", "FAIL SAFE", "MISC", "MISCELLANEOUS", "UNKNOWN", "UNASSIGNED"}:
        return "unknown_bucket"
    return None


def dbf_records(path: Path) -> list[dict[str, str]]:
    with path.open("rb") as fh:
        header = fh.read(32)
        if len(header) < 32:
            raise ValueError(f"Invalid DBF header: {path}")
        record_count = struct.unpack("<I", header[4:8])[0]
        header_len = struct.unpack("<H", header[8:10])[0]
        record_len = struct.unpack("<H", header[10:12])[0]

        fields: list[tuple[str, int, int]] = []
        offset = 1
        while True:
            descriptor = fh.read(32)
            if not descriptor:
                raise ValueError(f"DBF field descriptor terminator not found: {path}")
            if descriptor[0] == 0x0D:
                break
            name = descriptor[:11].split(b"\x00", 1)[0].decode("ascii", "ignore")
            length = int(descriptor[16])
            fields.append((name, offset, length))
            offset += length

        fh.seek(header_len)
        rows: list[dict[str, str]] = []
        for _ in range(record_count):
            record = fh.read(record_len)
            if len(record) < record_len:
                break
            if record[:1] == b"*":
                continue
            row: dict[str, str] = {}
            for name, start, length in fields:
                row[name] = record[start : start + length].decode("latin1", "ignore").strip()
            rows.append(row)
    return rows


def load_sbe2006(path: Path) -> tuple[list[dict[str, str]], dict[tuple[str, str], list[dict[str, str]]]]:
    rows = dbf_records(path)
    index: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        county = norm(row.get("County"))
        if not county:
            continue
        for field in ("Precinct", "SEIMS_Code", "SEIMS_Desc"):
            value = norm(row.get(field))
            if value:
                index.setdefault((county, value), []).append(row)
                index.setdefault((county, norm_name(value)), []).append(row)
                index.setdefault((county, compact(value)), []).append(row)
    return rows, index


def strip_split_suffix(value: str) -> str:
    text = norm_name(value)
    text = re.sub(r"\b[YZ]\b$", "", text).strip()
    text = re.sub(r"\b[A-Z]\b$", "", text).strip()
    return text


def split_component_match(raw_precinct: str, sbe_row: dict[str, str]) -> bool:
    raw_key = norm_name(raw_precinct)
    raw_base = strip_split_suffix(raw_precinct)
    if not raw_key and not raw_base:
        return False
    combined_values = [sbe_row.get("Precinct", ""), sbe_row.get("SEIMS_Desc", ""), sbe_row.get("SEIMS_Code", "")]
    for value in combined_values:
        target = norm_name(value)
        if not target:
            continue
        if raw_key == target or raw_base == target:
            return True
        target_tokens = set(target.split())
        raw_tokens = set(raw_key.split())
        raw_base_tokens = set(raw_base.split())
        if raw_tokens and raw_tokens.issubset(target_tokens):
            return True
        if raw_base_tokens and raw_base_tokens.issubset(target_tokens):
            return True
    return False


def best_sbe_hit(
    county: str,
    precinct: str,
    sbe_index: dict[tuple[str, str], list[dict[str, str]]],
) -> tuple[str, dict[str, str] | None]:
    candidates = [norm(precinct), norm_name(precinct), compact(precinct)]
    for key in candidates:
        hits = sbe_index.get((county, key)) or []
        if hits:
            return "sbe2006_exact", hits[0]
    return "", None


def classify_row(row: dict[str, str], sbe_index: dict[tuple[str, str], list[dict[str, str]]]) -> dict[str, str]:
    county, raw_precinct = split_key(row.get("raw_precinct_key"))
    era_county, era_precinct = split_key(row.get("era_precinct_key"))
    county = county or era_county

    bucket = non_geo_category(raw_precinct, county)
    if bucket:
        classification = "non_geographic_bucket"
        category = bucket
        confidence = "high"
        hit: dict[str, str] | None = None
        evidence = f"matched non-geographic token category {bucket}"
    else:
        match_kind, hit = best_sbe_hit(county, raw_precinct, sbe_index)
        if hit:
            classification = "geographic_sbe2006"
            category = "sbe2006_exact_precinct_or_code"
            confidence = "high"
            evidence = "raw leftover key matches SBE2006 Precinct/SEIMS_Code/SEIMS_Desc"
        else:
            match_kind, hit = best_sbe_hit(county, era_precinct, sbe_index)
            if hit and split_component_match(raw_precinct, hit):
                classification = "resolvable_sbe2006_alias"
                category = "sbe2006_split_component"
                confidence = "high"
                evidence = "raw key is a component/suffix split of the matched SBE2006 era precinct"
            elif hit:
                classification = "resolvable_sbe2006_alias"
                category = "sbe2006_era_key_alias"
                confidence = "medium"
                evidence = "era_precinct_key matches SBE2006, but raw key is not an obvious component"
            else:
                classification = "likely_geographic_precinct"
                category = "unverified_geographic"
                confidence = "low"
                evidence = "not a known election bucket and no SBE2006 DBF match found"

    out = dict(row)
    out.update(
        {
            "county": county,
            "raw_precinct": raw_precinct,
            "classification": classification,
            "category": category,
            "confidence": confidence,
            "sbe2006_precinct": norm(hit.get("Precinct")) if hit else "",
            "sbe2006_seims_code": norm(hit.get("SEIMS_Code")) if hit else "",
            "sbe2006_seims_desc": norm(hit.get("SEIMS_Desc")) if hit else "",
            "evidence": evidence,
        }
    )
    return out


def load_leftovers(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_detail(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "year",
        "raw_precinct_key",
        "era_precinct_key",
        "canonical_precinct_key",
        "old_share",
        "county",
        "raw_precinct",
        "classification",
        "category",
        "confidence",
        "sbe2006_precinct",
        "sbe2006_seims_code",
        "sbe2006_seims_desc",
        "evidence",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def summarize(
    rows: list[dict[str, str]],
    sbe_record_count: int,
    smoke_dir: Path,
    leftovers_path: Path,
    sbe2006_dbf_path: Path,
) -> dict[str, Any]:
    total_leftovers = len(rows)
    non_geo = sum(1 for row in rows if row["classification"] == "non_geographic_bucket")
    geographic = total_leftovers - non_geo
    category_counts = Counter(row["category"] for row in rows)
    class_counts = Counter(row["classification"] for row in rows)
    county_category_counts = Counter((row["county"], row["category"]) for row in rows)

    smoke_meta: dict[str, Any] = {}
    smoke_files = sorted(path for path in smoke_dir.glob("*.json") if path.name != "manifest.json")
    if smoke_files:
        payload = json.loads(smoke_files[0].read_text(encoding="utf-8"))
        meta = payload.get("meta") or {}
        matched = int(meta.get("matched_precinct_keys") or 0)
        total = int(meta.get("total_precinct_keys") or 0)
        raw_unmatched = max(total - matched, 0)
        preclassified_bucket_unmatched = max(raw_unmatched - total_leftovers, 0)
        geographic_total = matched + geographic
        smoke_meta = {
            "raw_matched_precinct_keys": matched,
            "raw_total_precinct_keys": total,
            "raw_unmatched_precinct_keys": raw_unmatched,
            "raw_match_coverage_pct": round((matched / total * 100.0) if total else 0.0, 2),
            "classified_leftover_precinct_keys": total_leftovers,
            "classified_non_geographic_leftover_keys": non_geo,
            "classified_geographic_leftover_keys": geographic,
            "preclassified_non_geographic_or_filtered_unmatched_keys": preclassified_bucket_unmatched,
            "geographic_matched_precinct_keys": matched,
            "geographic_total_precinct_keys": geographic_total,
            "geographic_unmatched_precinct_keys": geographic,
            "geographic_match_coverage_pct": round((matched / geographic_total * 100.0) if geographic_total else 0.0, 2),
        }

    return {
        "leftovers_csv": display_path(leftovers_path),
        "sbe2006_shapefile": display_path(sbe2006_dbf_path.with_suffix(".shp")),
        "sbe2006_dbf": display_path(sbe2006_dbf_path),
        "sbe2006_records": sbe_record_count,
        "total_leftovers": total_leftovers,
        "non_geographic_leftovers": non_geo,
        "geographic_or_resolvable_leftovers": geographic,
        "by_classification": dict(sorted(class_counts.items())),
        "by_category": dict(sorted(category_counts.items())),
        "by_county_category": [
            {"county": county, "category": category, "count": count}
            for (county, category), count in sorted(county_category_counts.items())
        ],
        "coverage": smoke_meta,
        "examples": {
            "non_geographic": [row["raw_precinct_key"] for row in rows if row["classification"] == "non_geographic_bucket"][:20],
            "true_or_resolvable_geographic": [
                row["raw_precinct_key"]
                for row in rows
                if row["classification"] != "non_geographic_bucket"
            ][:20],
        },
    }


def update_smoke_metadata(smoke_dir: Path, summary: dict[str, Any], detail_path: Path, summary_path: Path) -> list[str]:
    coverage = summary.get("coverage") or {}
    if not coverage:
        return []
    updated: list[str] = []
    for path in sorted(smoke_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.setdefault("meta", {})
        meta["raw_match_coverage_pct"] = coverage["raw_match_coverage_pct"]
        meta["raw_matched_precinct_keys"] = coverage["raw_matched_precinct_keys"]
        meta["raw_total_precinct_keys"] = coverage["raw_total_precinct_keys"]
        meta["raw_unmatched_precinct_keys"] = coverage["raw_unmatched_precinct_keys"]
        meta["geographic_match_coverage_pct"] = coverage["geographic_match_coverage_pct"]
        meta["geographic_matched_precinct_keys"] = coverage["geographic_matched_precinct_keys"]
        meta["geographic_total_precinct_keys"] = coverage["geographic_total_precinct_keys"]
        meta["geographic_unmatched_precinct_keys"] = coverage["geographic_unmatched_precinct_keys"]
        meta["classified_leftover_precinct_keys"] = coverage["classified_leftover_precinct_keys"]
        meta["classified_non_geographic_leftover_keys"] = coverage["classified_non_geographic_leftover_keys"]
        meta["classified_geographic_leftover_keys"] = coverage["classified_geographic_leftover_keys"]
        meta["preclassified_non_geographic_or_filtered_unmatched_keys"] = coverage[
            "preclassified_non_geographic_or_filtered_unmatched_keys"
        ]
        meta["leftover_classification_csv"] = detail_path.relative_to(ROOT).as_posix()
        meta["leftover_classification_summary"] = summary_path.relative_to(ROOT).as_posix()
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        updated.append(path.relative_to(ROOT).as_posix())
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leftovers-csv", type=Path, default=DEFAULT_LEFTOVERS)
    parser.add_argument("--sbe2006-dbf", type=Path, default=DEFAULT_SBE2006_DBF)
    parser.add_argument("--smoke-dir", type=Path, default=DEFAULT_SMOKE_DIR)
    parser.add_argument("--detail-csv", type=Path, default=DEFAULT_DETAIL)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--update-smoke-meta", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sbe_rows, sbe_index = load_sbe2006(args.sbe2006_dbf)
    classified = [classify_row(row, sbe_index) for row in load_leftovers(args.leftovers_csv)]
    classified.sort(key=lambda row: (row["classification"], row["category"], row["county"], row["raw_precinct"]))
    write_detail(args.detail_csv, classified)
    summary = summarize(classified, len(sbe_rows), args.smoke_dir, args.leftovers_csv, args.sbe2006_dbf)
    if args.update_smoke_meta:
        summary["updated_smoke_files"] = update_smoke_metadata(
            args.smoke_dir,
            summary,
            args.detail_csv,
            args.summary_json,
        )
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
