"""Convert Census/NC block equivalency files to atlas block crosswalks.

The source files assign every North Carolina 2020 Census block to a
congressional or legislative district. Outputs use the common schema consumed
by the atlas aggregation scripts.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EXPECTED_NC_BLOCKS = 236_638


@dataclass(frozen=True)
class Spec:
    source: str
    output: str
    district_column: str
    district_type: str
    district_prefix: str
    district_width: int
    target_year: int
    plan_id: str
    plan_label: str


SPECS = (
    Spec("37_NC_CD118.txt", "block20_to_cd118.csv", "CDFP", "congressional", "CD", 2, 2022,
         "census_bef_cd118", "Census Block Equivalency File - 118th Congress"),
    Spec("37_NC_CD119.txt", "block20_to_cd119.csv", "CDFP", "congressional", "CD", 2, 2024,
         "census_bef_cd119", "Census Block Equivalency File - 119th Congress"),
    Spec("CD120_37.txt", "block20_to_cd2026_sl2025_95.csv", "CDFP", "congressional", "CD", 2, 2026,
         "sl2025_95_cd120", "SL 2025-95 - 120th Congress"),
    Spec("37_NC_SLDL22.txt", "block20_to_2022_state_house.csv", "SLDLST", "state_house", "HD", 3, 2022,
         "census_bef_sldl22", "Census Block Equivalency File - 2022 State House"),
    Spec("37_NC_SLDU22.txt", "block20_to_2022_state_senate.csv", "SLDUST", "state_senate", "SD", 2, 2022,
         "census_bef_sldu22", "Census Block Equivalency File - 2022 State Senate"),
    Spec("37_NC_SLDL24.txt", "block20_to_2024_state_house.csv", "SLDLST", "state_house", "HD", 3, 2024,
         "census_bef_sldl24", "Census Block Equivalency File - 2024 State House"),
    Spec("37_NC_SLDU24.txt", "block20_to_2024_state_senate.csv", "SLDUST", "state_senate", "SD", 2, 2024,
         "census_bef_sldu24", "Census Block Equivalency File - 2024 State Senate"),
)


OUTPUT_FIELDS = (
    "block_geoid20",
    "countyfp20",
    "district",
    "district_geoid",
    "district_name",
    "district_code",
    "district_label",
    "district_type",
    "target_year",
    "plan_id",
    "plan_label",
    "area_weight",
)


def convert(spec: Spec) -> None:
    source = ROOT / "data" / spec.source
    output = ROOT / "data" / "crosswalks" / spec.output
    if not source.exists():
        raise FileNotFoundError(source)

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    with source.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, skipinitialspace=True)
        fields = {field.strip() for field in (reader.fieldnames or [])}
        if "GEOID" not in fields or spec.district_column not in fields:
            raise ValueError(f"Unexpected columns in {source}: {reader.fieldnames}")

        for line_number, raw in enumerate(reader, start=2):
            row = {str(key).strip(): value for key, value in raw.items() if key is not None}
            block = str(row.get("GEOID") or "").strip().zfill(15)
            if len(block) != 15 or not block.isdigit() or not block.startswith("37"):
                raise ValueError(f"Invalid NC block GEOID at {source}:{line_number}: {block!r}")
            if block in seen:
                raise ValueError(f"Duplicate block GEOID at {source}:{line_number}: {block}")
            seen.add(block)

            source_district = str(row.get(spec.district_column) or "").strip()
            if not source_district.isdigit():
                raise ValueError(
                    f"Invalid district at {source}:{line_number}: {source_district!r}"
                )
            district_number = int(source_district)
            district_code = f"{district_number:0{spec.district_width}d}"
            district_kind = {
                "congressional": "Congressional District",
                "state_house": "State House District",
                "state_senate": "State Senate District",
            }[spec.district_type]
            rows.append(
                {
                    "block_geoid20": block,
                    "countyfp20": block[2:5],
                    "district": district_code,
                    "district_geoid": f"37{district_code}",
                    "district_name": f"{district_kind} {district_number}",
                    "district_code": district_code,
                    "district_label": f"{spec.district_prefix}-{district_code}",
                    "district_type": spec.district_type,
                    "target_year": spec.target_year,
                    "plan_id": spec.plan_id,
                    "plan_label": spec.plan_label,
                    "area_weight": "1.0",
                }
            )

    if len(rows) != EXPECTED_NC_BLOCKS:
        raise ValueError(
            f"{source} has {len(rows):,} unique blocks; expected {EXPECTED_NC_BLOCKS:,}"
        )

    rows.sort(key=lambda row: str(row["block_geoid20"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows):,} blocks: {output.relative_to(ROOT)}")


def main() -> None:
    for spec in SPECS:
        convert(spec)


if __name__ == "__main__":
    main()
