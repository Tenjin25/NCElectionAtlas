import json
import re
from collections import defaultdict
from pathlib import Path


COMMON_PRECINCT_WORDS = [
    "PRECINCT",
    "PCT",
    "PRCT",
    "VTD",
    "WARD",
]


def norm(text: object) -> str:
    return str(text or "").upper().strip()


def compact(text: object) -> str:
    t = norm(text)
    return "".join(ch for ch in t if ch.isalnum())


def normalize_precinct_token(text: object) -> str:
    t = norm(text)
    for word in COMMON_PRECINCT_WORDS:
        t = t.replace(word, " ")
    t = t.replace("-", " ").replace("_", " ").replace(".", " ")
    t = " ".join(t.split())
    return t


def extract_code_name_aliases(raw: object) -> list[str]:
    aliases = set()
    p = norm(raw)
    pn = normalize_precinct_token(raw)
    aliases.add(p)
    aliases.add(compact(p))
    aliases.add(pn)
    aliases.add(compact(pn))

    if "_" in p:
        code, name = p.split("_", 1)
        aliases.add(code.strip())
        aliases.add(name.strip())
        aliases.add(compact(code))
        aliases.add(compact(name))

    parts = pn.split()
    if parts:
        first = parts[0]
        if any(ch.isdigit() for ch in first):
            aliases.add(first)
            aliases.add(compact(first))
            rest = " ".join(parts[1:]).strip()
            if rest:
                aliases.add(rest)
                aliases.add(compact(rest))

    s = p.replace("-", ".")
    if "." in s:
        a, b = s.split(".", 1)
        if a.isdigit() and b.isdigit():
            aliases.add(f"{int(a)}.{int(b)}")
            aliases.add(f"{int(a):02d}.{int(b)}")
            aliases.add(f"{int(a):02d}{int(b)}")
            aliases.add(f"{int(a):02d}{int(b):02d}")
    if p.isdigit():
        aliases.add(str(int(p)))
        aliases.add(p.zfill(4))

    return [a for a in aliases if a]


def build_precinct_alias_index(voting_geojson_path: Path) -> dict[str, dict[str, set[str]]]:
    geo = json.loads(voting_geojson_path.read_text(encoding="utf-8"))
    county_map: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for feature in geo.get("features", []):
        props = feature.get("properties", {})
        county = norm(props.get("county_nam", ""))
        prec_id = norm(props.get("prec_id", ""))
        enr_desc = norm(props.get("enr_desc", ""))
        if not county or not prec_id:
            continue
        aliases = set()
        aliases.update(extract_code_name_aliases(prec_id))
        if enr_desc:
            aliases.update(extract_code_name_aliases(enr_desc))
            aliases.update(extract_code_name_aliases(f"{prec_id}_{enr_desc}"))
            aliases.update(extract_code_name_aliases(f"{prec_id} {enr_desc}"))

        for alias in aliases:
            county_map[county][alias].add(prec_id)

    return county_map


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    in_path = repo_root / "data" / "Voting_Precincts.geojson"
    out_path = repo_root / "data" / "precinct_alias_index.json"

    alias_index = build_precinct_alias_index(in_path)
    payload = {
        "version": 1,
        "generated_from": ["data/Voting_Precincts.geojson"],
        "counties": {
            county: {
                alias: sorted(values)
                for alias, values in sorted(alias_map.items())
            }
            for county, alias_map in sorted(alias_index.items())
        },
    }

    out_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
