"""
Aggregate Redistricting Data Hub block-level CVAP (ACS 2020-2024 special tab) onto atlas geographies.

Inputs
  - Block CVAP CSV (one row per 2020 Census block GEOID20)
    Default: data/nc_cvap_2024_2020_b_csv/nc_cvap_2024_2020_b.csv

  - Crosswalk CSVs keyed by 2020 block GEOID20
    Defaults (if present):
      - data/crosswalks/block20_to_precinct.csv
      - data/crosswalks/block20_to_cd118.csv
      - data/crosswalks/block20_to_cd119.csv
      - data/crosswalks/block20_to_2022_state_house.csv
      - data/crosswalks/block20_to_2024_state_house.csv
      - data/crosswalks/block20_to_2022_state_senate.csv
      - data/crosswalks/block20_to_2024_state_senate.csv

Outputs
  - CSV aggregates written to an output directory (default: data/cvap_aggregates)

Notes
  - District crosswalks include an area_weight column; precinct crosswalk does not.
  - This script does not change the running atlas until you wire these outputs in.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--cvap",
        default="data/nc_cvap_2024_2020_b_csv/nc_cvap_2024_2020_b.csv",
        help="Path to RDH block-level CVAP CSV keyed by GEOID20.",
    )
    p.add_argument(
        "--outdir",
        default="data/cvap_aggregates",
        help="Directory to write aggregated outputs.",
    )
    p.add_argument(
        "--targets",
        default="all",
        help=(
            "Comma-separated list of outputs to build. "
            "Options: all, county, precinct, cd118, cd119, state_house_2022, state_house_2024, state_senate_2022, state_senate_2024. "
            "Example: county,cd119"
        ),
    )
    p.add_argument(
        "--fields",
        default="",
        help=(
            "Comma-separated list of CVAP CSV fields to aggregate (default: all C_* and CVAP_* fields). "
            "Example: CVAP_TOT24,CVAP_HSP24,CVAP_WHT24,CVAP_BLA24"
        ),
    )
    p.add_argument(
        "--chunksize",
        type=int,
        default=250_000,
        help="Rows per chunk when reading CVAP via pandas (default: 250000).",
    )
    p.add_argument(
        "--skip-missing-crosswalks",
        action="store_true",
        help="Skip default crosswalks that are not found instead of failing.",
    )
    p.add_argument(
        "--county-geojson",
        default="data/census/tl_2020_37_county20.geojson",
        help="Optional path to a county GeoJSON with GEOID20/NAME20 for labeling county outputs.",
    )
    return p.parse_args()


def _to_float(raw: object, default: float = 0.0) -> float:
    s = ("" if raw is None else str(raw)).strip()
    if s == "":
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _to_int(raw: object, default: int = 0) -> int:
    s = ("" if raw is None else str(raw)).strip()
    if s == "":
        return default
    try:
        return int(float(s))
    except ValueError:
        return default


def read_cvap_header(cvap_path: Path) -> List[str]:
    with cvap_path.open("r", newline="", encoding="utf-8", errors="ignore") as f:
        r = csv.reader(f)
        header = next(r, [])
    return [h.strip() for h in header if h is not None]


def default_cvap_fields(header: Sequence[str]) -> List[str]:
    fields = [h for h in header if h.startswith("C_") or h.startswith("CVAP_")]
    return fields


def iter_cvap_rows(
    cvap_path: Path, usecols: Sequence[str], chunksize: int
) -> Iterable[Tuple[str, List[int]]]:
    """
    Yield (block_geoid20, values[]) for selected fields in the CVAP CSV.
    Uses pandas chunking if available, else csv.DictReader.
    """
    try:
        import pandas as pd  # type: ignore
    except Exception:
        pd = None

    if pd is None:
        with cvap_path.open("r", newline="", encoding="utf-8", errors="ignore") as f:
            r = csv.DictReader(f)
            for row in r:
                geoid = (row.get("GEOID20") or "").strip()
                if not geoid:
                    continue
                vals = [_to_int(row.get(col)) for col in usecols]
                yield geoid, vals
        return

    usecols_full = ["GEOID20", *usecols]
    for chunk in pd.read_csv(
        cvap_path,
        usecols=usecols_full,
        dtype={c: "string" for c in usecols_full},
        chunksize=chunksize,
        low_memory=True,
    ):
        geoids = chunk["GEOID20"].astype("string").fillna("")
        col_lists = []
        for col in usecols:
            col_lists.append(chunk[col].astype("string").fillna("0"))
        for i in range(len(chunk.index)):
            geoid = (geoids.iat[i] or "").strip()
            if not geoid:
                continue
            vals = []
            for col_ser in col_lists:
                vals.append(_to_int(col_ser.iat[i]))
            yield geoid, vals


def load_block_cvap(cvap_path: Path, fields: Sequence[str], chunksize: int) -> Dict[str, List[int]]:
    block_map: Dict[str, List[int]] = {}
    n = 0
    for geoid, vals in iter_cvap_rows(cvap_path, fields, chunksize):
        block_map[geoid] = vals
        n += 1
        if n % 250_000 == 0:
            print(f"Loaded blocks: {n:,}")
    print(f"Loaded blocks: {n:,}")
    return block_map


def _county_key_from_block_geoid20(geoid20: str) -> Optional[Tuple[str, str, str]]:
    g = (geoid20 or "").strip()
    if len(g) < 5:
        return None
    statefp = g[0:2]
    countyfp = g[2:5]
    if not (statefp.isdigit() and countyfp.isdigit()):
        return None
    return statefp, countyfp, f"{statefp}{countyfp}"


def load_cvap_data(
    cvap_path: Path,
    fields: Sequence[str],
    chunksize: int,
    *,
    store_blocks: bool,
) -> Tuple[Dict[str, List[int]], Dict[str, List[int]]]:
    """
    Returns (block_map, county_sums).
    - block_map keys: GEOID20 (block), only populated when store_blocks=True
    - county_sums keys: GEOID20 (5-digit state+county)
    """
    block_map: Dict[str, List[int]] = {} if store_blocks else {}
    county_sums: Dict[str, List[int]] = {}
    n = 0
    for geoid, vals in iter_cvap_rows(cvap_path, fields, chunksize):
        if store_blocks:
            block_map[geoid] = vals
        ck = _county_key_from_block_geoid20(geoid)
        if ck:
            _, _, county_geoid = ck
            acc = county_sums.get(county_geoid)
            if acc is None:
                county_sums[county_geoid] = list(vals)
            else:
                for i, v in enumerate(vals):
                    acc[i] += int(v)
        n += 1
        if n % 250_000 == 0:
            print(f"Loaded CVAP rows: {n:,}")
    print(f"Loaded CVAP rows: {n:,}")
    return block_map, county_sums


def load_county_name_map(path: Path) -> Dict[str, str]:
    """
    Build {county_geoid20(5-digit): county_name} from a county GeoJSON.
    Expects properties: GEOID20 + NAME20 (NC TIGER-style).
    """
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        feats = obj.get("features") if isinstance(obj, dict) else None
        if not isinstance(feats, list):
            return {}
        out: Dict[str, str] = {}
        for f in feats:
            if not isinstance(f, dict):
                continue
            props = f.get("properties")
            if not isinstance(props, dict):
                continue
            geoid = (props.get("GEOID20") or "").strip()
            name = (props.get("NAME20") or "").strip()
            if len(geoid) == 5 and name:
                out[geoid] = name
        return out
    except Exception:
        return {}


def write_county_aggregate(
    *,
    out_path: Path,
    fields: Sequence[str],
    county_sums: Dict[str, List[int]],
    county_names: Dict[str, str],
) -> None:
    header = ["statefp20", "countyfp20", "county_geoid20", "county_name", *fields]
    rows: List[List[object]] = []
    for county_geoid in sorted(county_sums.keys()):
        statefp = county_geoid[0:2]
        countyfp = county_geoid[2:5]
        name = county_names.get(county_geoid, "")
        rows.append([statefp, countyfp, county_geoid, name, *county_sums[county_geoid]])
    write_csv(out_path, header, rows)


def parse_targets(raw: str) -> List[str]:
    t = [s.strip().lower() for s in (raw or "").split(",") if s.strip()]
    if not t:
        return ["all"]
    if "all" in t:
        return [
            "county",
            "precinct",
            "cd118",
            "cd119",
            "state_house_2022",
            "state_house_2024",
            "state_senate_2022",
            "state_senate_2024",
        ]
    return t


def spec_matches_targets(spec: CrosswalkSpec, targets: Sequence[str]) -> bool:
    name = spec.name
    if "precinct" in targets and name.startswith("precinct_"):
        return True
    if "cd118" in targets and name.startswith("cd118_"):
        return True
    if "cd119" in targets and name.startswith("cd119_"):
        return True
    if "state_house_2022" in targets and name.startswith("state_house_2022_"):
        return True
    if "state_house_2024" in targets and name.startswith("state_house_2024_"):
        return True
    if "state_senate_2022" in targets and name.startswith("state_senate_2022_"):
        return True
    if "state_senate_2024" in targets and name.startswith("state_senate_2024_"):
        return True
    return False


@dataclass(frozen=True)
class CrosswalkSpec:
    name: str
    path: Path
    group_key: str
    id_columns: Tuple[str, ...]
    weight_column: Optional[str] = None
    block_column: str = "block_geoid20"


def default_crosswalk_specs(root: Path) -> List[CrosswalkSpec]:
    cw = root / "data" / "crosswalks"
    return [
        CrosswalkSpec(
            name="precinct_2020",
            path=cw / "block20_to_precinct.csv",
            group_key="precinct_id",
            id_columns=("countyfp20", "precinct_id"),
            weight_column=None,
        ),
        CrosswalkSpec(
            name="cd118_2022_lines",
            path=cw / "block20_to_cd118.csv",
            group_key="district",
            id_columns=(
                "district_type",
                "target_year",
                "plan_id",
                "district",
                "district_code",
                "district_label",
                "district_geoid",
                "district_name",
            ),
            weight_column="area_weight",
        ),
        CrosswalkSpec(
            name="cd119_2024_lines",
            path=cw / "block20_to_cd119.csv",
            group_key="district",
            id_columns=(
                "district_type",
                "target_year",
                "plan_id",
                "district",
                "district_code",
                "district_label",
                "district_geoid",
                "district_name",
            ),
            weight_column="area_weight",
        ),
        CrosswalkSpec(
            name="state_house_2022_lines",
            path=cw / "block20_to_2022_state_house.csv",
            group_key="district",
            id_columns=(
                "district_type",
                "target_year",
                "plan_id",
                "district",
                "district_code",
                "district_label",
                "district_geoid",
                "district_name",
            ),
            weight_column="area_weight",
        ),
        CrosswalkSpec(
            name="state_house_2024_lines",
            path=cw / "block20_to_2024_state_house.csv",
            group_key="district",
            id_columns=(
                "district_type",
                "target_year",
                "plan_id",
                "district",
                "district_code",
                "district_label",
                "district_geoid",
                "district_name",
            ),
            weight_column="area_weight",
        ),
        CrosswalkSpec(
            name="state_senate_2022_lines",
            path=cw / "block20_to_2022_state_senate.csv",
            group_key="district",
            id_columns=(
                "district_type",
                "target_year",
                "plan_id",
                "district",
                "district_code",
                "district_label",
                "district_geoid",
                "district_name",
            ),
            weight_column="area_weight",
        ),
        CrosswalkSpec(
            name="state_senate_2024_lines",
            path=cw / "block20_to_2024_state_senate.csv",
            group_key="district",
            id_columns=(
                "district_type",
                "target_year",
                "plan_id",
                "district",
                "district_code",
                "district_label",
                "district_geoid",
                "district_name",
            ),
            weight_column="area_weight",
        ),
    ]


def aggregate_to_crosswalk(
    *,
    block_cvap: Dict[str, List[int]],
    fields: Sequence[str],
    spec: CrosswalkSpec,
) -> Tuple[List[str], List[List[object]], Dict[str, int]]:
    """
    Return (header, rows, stats).
    header includes spec.id_columns + fields.
    rows are in stable key order.
    """
    sums: Dict[str, List[float]] = {}
    ids: Dict[str, List[object]] = {}
    stats = {
        "crosswalk_rows": 0,
        "missing_block": 0,
        "weighted_rows": 0,
        "groups": 0,
    }

    with spec.path.open("r", newline="", encoding="utf-8", errors="ignore") as f:
        r = csv.DictReader(f)
        for row in r:
            stats["crosswalk_rows"] += 1
            block = (row.get(spec.block_column) or "").strip()
            if not block:
                continue
            vals = block_cvap.get(block)
            if vals is None:
                stats["missing_block"] += 1
                continue

            key = (row.get(spec.group_key) or "").strip()
            if key == "":
                continue

            w = 1.0
            if spec.weight_column:
                w = _to_float(row.get(spec.weight_column), default=1.0)
            stats["weighted_rows"] += 1

            if key not in sums:
                sums[key] = [0.0 for _ in fields]
                ids[key] = [(row.get(c) or "").strip() for c in spec.id_columns]

            acc = sums[key]
            for i, v in enumerate(vals):
                acc[i] += float(v) * w

    header = [*spec.id_columns, *fields]
    out_rows: List[List[object]] = []
    for key in sorted(sums.keys(), key=lambda s: (len(s), s)):
        base = ids.get(key) or [key]
        acc = sums[key]
        # Round to 2 decimals only if fractional appears; keep ints if whole.
        rendered: List[object] = []
        for x in acc:
            if abs(x - round(x)) < 1e-9:
                rendered.append(int(round(x)))
            else:
                rendered.append(round(x, 2))
        out_rows.append([*base, *rendered])

    stats["groups"] = len(out_rows)
    return header, out_rows, stats


def write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(list(header))
        for row in rows:
            w.writerow(list(row))


def main() -> int:
    args = parse_args()
    cvap_path = Path(args.cvap)
    outdir = Path(args.outdir)
    if not cvap_path.exists():
        raise FileNotFoundError(f"CVAP CSV not found: {cvap_path}")

    header = read_cvap_header(cvap_path)
    if not header or "GEOID20" not in header:
        raise RuntimeError(f"Unexpected CVAP header (missing GEOID20): {cvap_path}")

    if args.fields.strip():
        fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    else:
        fields = default_cvap_fields(header)

    missing = [f for f in fields if f not in header]
    if missing:
        raise RuntimeError(f"Requested fields not found in CVAP CSV: {missing}")

    print(f"CVAP input: {cvap_path}")
    print(f"Aggregating fields: {len(fields)}")
    targets = parse_targets(args.targets)
    print(f"Targets: {', '.join(targets)}")

    need_blocks = any(t != "county" for t in targets)

    block_cvap, county_sums = load_cvap_data(
        cvap_path, fields, args.chunksize, store_blocks=need_blocks
    )

    if "county" in targets:
        county_geojson = Path(args.county_geojson) if args.county_geojson else Path("")
        county_names = load_county_name_map(county_geojson) if county_geojson else {}
        out_path = outdir / "county_2020__cvap24.csv"
        write_county_aggregate(
            out_path=out_path,
            fields=fields,
            county_sums=county_sums,
            county_names=county_names,
        )
        print(f"\nWrote: {out_path} | counties={len(county_sums):,}")

    if not need_blocks:
        print("\nDone.")
        return 0

    specs = default_crosswalk_specs(Path("."))
    for spec in [s for s in specs if spec_matches_targets(s, targets)]:
        if not spec.path.exists():
            msg = f"Crosswalk missing: {spec.path} ({spec.name})"
            if args.skip_missing_crosswalks:
                print(f"Skipping: {msg}")
                continue
            raise FileNotFoundError(msg)

        out_path = outdir / f"{spec.name}__cvap24.csv"
        print(f"\nCrosswalk: {spec.path}")
        header_out, rows_out, stats = aggregate_to_crosswalk(
            block_cvap=block_cvap, fields=fields, spec=spec
        )
        write_csv(out_path, header_out, rows_out)
        print(
            f"Wrote: {out_path} | groups={stats['groups']:,} rows={stats['crosswalk_rows']:,} "
            f"missing_blocks={stats['missing_block']:,}"
        )

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
