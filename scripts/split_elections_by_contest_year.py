import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    src = root / "data" / "nc_elections_aggregated.json"
    out_dir = root / "data" / "contests"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(src.read_text(encoding="utf-8"))
    by_year = data.get("results_by_year", {})

    manifest = []
    files_written = 0

    for year, year_node in by_year.items():
        for office, office_node in year_node.items():
            general = (office_node or {}).get("general", {})
            results = general.get("results", {}) or {}
            if not results:
                continue

            rows = []
            for precinct_key, r in results.items():
                rows.append(
                    {
                        "county": precinct_key,
                        "dem_votes": r.get("dem_votes", 0),
                        "rep_votes": r.get("rep_votes", 0),
                        "other_votes": r.get("other_votes", 0),
                        "total_votes": r.get("total_votes", 0),
                        "dem_candidate": r.get("dem_candidate", ""),
                        "rep_candidate": r.get("rep_candidate", ""),
                        "margin": r.get("margin", 0),
                        "margin_pct": r.get("margin_pct", 0),
                        "winner": r.get("winner", ""),
                        "color": ((r.get("competitiveness") or {}).get("color") or ""),
                    }
                )

            payload = {
                "year": int(year),
                "contest_type": office,
                "rows": rows,
            }
            out_path = out_dir / f"{office}_{year}.json"
            out_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            files_written += 1
            manifest.append(
                {
                    "year": int(year),
                    "contest_type": office,
                    "file": out_path.name,
                    "rows": len(rows),
                }
            )

    manifest.sort(key=lambda x: (x["year"], x["contest_type"]))
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"files": manifest}, indent=2), encoding="utf-8")

    print(f"Wrote {files_written} contest files to {out_dir}")
    print(f"Wrote manifest: {manifest_path}")


if __name__ == "__main__":
    main()
