#!/usr/bin/env python3
"""Build compact data/county_contests/*.json from OpenElections precinct CSVs.

These CSVs are the atlas input after SBE TSVs are converted with
tools/convert_to_openelections.py (county,precinct,office,district,party,candidate,votes).

County-facing map layers should load these 100-row slices instead of summing
crosswalked precinct rows, which can retain allocation residuals.

Judicial / nonpartisan ballot labels are remapped via
data/mappings/judicial_candidate_party_overrides.csv (same map used by the
pre-2018 judicial reaggregate path), so seats like 2018 Anglin stay OTHER and
DEM/REP margins stay correct.

Usage:
  python scripts/build_county_contests_from_oe.py
  python scripts/build_county_contests_from_oe.py --write
  python scripts/build_county_contests_from_oe.py --write --years 2018,2024
  python scripts/build_county_contests_from_oe.py --write --update-sidecars
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from add_csv_county_totals_to_contests import (  # noqa: E402
    CONTEST_DIR,
    JUDICIAL_PARTY_OVERRIDES,
    aggregate_county_totals,
    choose_office,
    contest_year,
    load_candidate_party_overrides,
    load_csv_by_office,
    json_candidate_buckets,
    norm,
    raw_csv_for_year,
)

DEFAULT_COUNTY_CONTEST_DIR = ROOT / "data" / "county_contests"
DEFAULT_JUDICIAL_OVERRIDES = JUDICIAL_PARTY_OVERRIDES


def load_manifest_entries() -> list[dict]:
    manifest_path = CONTEST_DIR / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = payload.get("files") if isinstance(payload, dict) else payload
    return [entry for entry in (files or []) if entry and not entry.get("scope")]


def override_hits_for_contest(
    payload: dict,
    raw_rows: list[dict[str, str]],
    year_overrides: dict[str, str],
) -> list[dict[str, str]]:
    """Return override rows that actually affect this contest's candidate set."""
    if not year_overrides:
        return []
    buckets = json_candidate_buckets(payload.get("rows") or [])
    raw_names = {norm(row.get("candidate")) for row in raw_rows if norm(row.get("candidate"))}
    relevant = set(buckets) | raw_names
    hits = []
    for candidate, party in sorted(year_overrides.items()):
        if candidate in relevant:
            hits.append({"candidate": candidate, "party": party})
    return hits


def write_compact_county_slice(
    *,
    out_dir: Path,
    filename: str,
    year: int,
    contest_type: str,
    office: str,
    csv_path: Path,
    county_totals: dict[str, dict],
    judicial_override_hits: list[dict[str, str]] | None = None,
    judicial_overrides_path: Path | None = None,
) -> Path:
    rows = [{"county": county, **totals} for county, totals in county_totals.items()]
    meta = {
        "source": "open_elections_csv",
        "office": office,
        "csv": str(csv_path.relative_to(ROOT)).replace("\\", "/"),
        "county_count": len(rows),
    }
    if judicial_overrides_path and judicial_overrides_path.exists():
        try:
            meta["judicial_party_overrides"] = str(
                judicial_overrides_path.relative_to(ROOT)
            ).replace("\\", "/")
        except ValueError:
            meta["judicial_party_overrides"] = str(judicial_overrides_path)
    if judicial_override_hits:
        meta["judicial_override_hits"] = judicial_override_hits
    compact = {
        "year": year,
        "contest_type": contest_type,
        "meta": meta,
        "county_totals": county_totals,
        "rows": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(json.dumps(compact, separators=(",", ":")) + "\n", encoding="utf-8")
    return out_path


def write_contest_sidecar(contest_path: Path, payload: dict, county_totals: dict[str, dict]) -> None:
    output = {key: value for key, value in payload.items() if key not in {"county_totals", "rows"}}
    output["county_totals"] = county_totals
    output["rows"] = payload.get("rows") or []
    contest_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


def write_county_manifest(out_dir: Path, written: list[dict], overrides_path: Path) -> None:
    try:
        overrides_label = str(overrides_path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        overrides_label = str(overrides_path)
    manifest = {
        "source": "open_elections_csv",
        "judicial_party_overrides": overrides_label,
        "files": [
            {
                "year": item["year"],
                "contest_type": item["contest_type"],
                "file": item["file"],
                "rows": item["county_count"],
                "office": item["office"],
                "csv": item["csv"],
                "judicial_override_hit_count": item.get("judicial_override_hit_count", 0),
            }
            for item in written
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build data/county_contests from OpenElections CSVs (SBE TSV conversions)."
    )
    parser.add_argument("--write", action="store_true", help="Write compact county contest JSON files.")
    parser.add_argument(
        "--update-sidecars",
        action="store_true",
        help="Also refresh county_totals inside data/contests/*.json.",
    )
    parser.add_argument("--years", default="", help="Optional comma-separated year filter.")
    parser.add_argument(
        "--out-dir",
        default="",
        help="Optional output directory (default: data/county_contests).",
    )
    parser.add_argument(
        "--judicial-overrides",
        default=str(DEFAULT_JUDICIAL_OVERRIDES),
        help="CSV mapping blank/nonpartisan judicial candidates to DEM/REP/OTHER "
        "(default: data/mappings/judicial_candidate_party_overrides.csv).",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_COUNTY_CONTEST_DIR
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    overrides_path = Path(args.judicial_overrides)
    if not overrides_path.is_absolute():
        overrides_path = ROOT / overrides_path

    year_filter = {int(value) for value in args.years.split(",") if value.strip()} if args.years else None
    csv_cache: dict[int, tuple[Path, dict[str, list[dict[str, str]]]]] = {}
    candidate_party_overrides = load_candidate_party_overrides(overrides_path)

    summary: dict[str, list] = {
        "written": [],
        "matched": [],
        "skipped": [],
        "sidecar_changed": [],
        "judicial_override_contests": [],
    }

    for entry in load_manifest_entries():
        filename = str(entry.get("file") or "").strip()
        if not filename or filename == "manifest.json":
            continue
        contest_path = CONTEST_DIR / filename
        if not contest_path.exists():
            summary["skipped"].append({"file": filename, "reason": "missing_contest_json"})
            continue

        payload = json.loads(contest_path.read_text(encoding="utf-8"))
        year = contest_year(contest_path, payload)
        if year is None or (year_filter and year not in year_filter):
            continue

        contest_type = str(
            payload.get("contest_type")
            or entry.get("contest_type")
            or re.sub(r"_\d{4}$", "", contest_path.stem)
        ).strip()

        if year not in csv_cache:
            csv_path = raw_csv_for_year(year)
            if csv_path is None:
                csv_cache[year] = (Path(), {})
            else:
                csv_cache[year] = (csv_path, load_csv_by_office(csv_path))
        csv_path, grouped = csv_cache[year]
        if not grouped:
            summary["skipped"].append({"file": filename, "reason": "missing_csv", "year": year})
            continue

        office, method = choose_office(payload, grouped)
        if not office:
            summary["skipped"].append({"file": filename, "reason": method, "year": year})
            continue

        year_overrides = candidate_party_overrides.get(year) or {}
        office_rows = grouped[office]
        judicial_hits = override_hits_for_contest(payload, office_rows, year_overrides)
        county_totals = aggregate_county_totals(
            payload,
            office_rows,
            year_overrides,
        )
        if len(county_totals) != 100:
            summary["skipped"].append(
                {
                    "file": filename,
                    "reason": f"county_count_{len(county_totals)}",
                    "office": office,
                    "year": year,
                }
            )
            continue

        matched = {
            "file": filename,
            "year": year,
            "contest_type": contest_type,
            "office": office,
            "method": method,
            "csv": str(csv_path.relative_to(ROOT)).replace("\\", "/"),
            "county_count": len(county_totals),
            "judicial_override_hit_count": len(judicial_hits),
        }
        summary["matched"].append(matched)
        if judicial_hits:
            summary["judicial_override_contests"].append(
                {
                    "file": filename,
                    "year": year,
                    "hits": judicial_hits,
                }
            )

        if args.write:
            write_compact_county_slice(
                out_dir=out_dir,
                filename=filename,
                year=year,
                contest_type=contest_type,
                office=office,
                csv_path=csv_path,
                county_totals=county_totals,
                judicial_override_hits=judicial_hits,
                judicial_overrides_path=overrides_path,
            )
            summary["written"].append(matched)

            if args.update_sidecars and payload.get("county_totals") != county_totals:
                write_contest_sidecar(contest_path, payload, county_totals)
                summary["sidecar_changed"].append(filename)

    if args.write:
        write_county_manifest(out_dir, summary["written"], overrides_path)

    try:
        out_dir_label = str(out_dir.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        out_dir_label = str(out_dir)
    try:
        overrides_label = str(overrides_path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        overrides_label = str(overrides_path)

    print(
        json.dumps(
            {
                "write": args.write,
                "update_sidecars": args.update_sidecars,
                "out_dir": out_dir_label,
                "judicial_overrides": overrides_label,
                "judicial_override_years": sorted(candidate_party_overrides.keys()),
                "judicial_override_contest_count": len(summary["judicial_override_contests"]),
                "matched_count": len(summary["matched"]),
                "written_count": len(summary["written"]),
                "skipped_count": len(summary["skipped"]),
                "sidecar_changed_count": len(summary["sidecar_changed"]),
                "judicial_override_contests": summary["judicial_override_contests"],
                "skipped": summary["skipped"],
                "sidecar_changed": summary["sidecar_changed"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
