import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    src = root / "data" / "nc_district_results_2022_lines.json"
    out_dir = root / "data" / "district_contests"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(src.read_text(encoding="utf-8"))
    by_year = data.get("results_by_year", {})

    manifest = []
    files_written = 0

    for year, year_node in by_year.items():
      for scope, scope_node in (year_node or {}).items():
        for contest_type, contest_node in (scope_node or {}).items():
          results = ((contest_node or {}).get("general") or {}).get("results") or {}
          if not results:
            continue

          payload = {
              "year": int(year),
              "scope": scope,
              "contest_type": contest_type,
              "meta": (contest_node or {}).get("meta") or {},
              "general": {"results": results},
          }
          out_name = f"{scope}_{contest_type}_{year}.json"
          out_path = out_dir / out_name
          out_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
          files_written += 1
          manifest.append(
              {
                  "year": int(year),
                  "scope": scope,
                  "contest_type": contest_type,
                  "file": out_name,
                  "districts": len(results),
              }
          )

    manifest.sort(key=lambda x: (x["year"], x["scope"], x["contest_type"]))
    (out_dir / "manifest.json").write_text(
        json.dumps({"files": manifest}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {files_written} district slice files to {out_dir}")


if __name__ == "__main__":
    main()
