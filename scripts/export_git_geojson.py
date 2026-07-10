from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write a tracked file from a git revision to a local path."
    )
    parser.add_argument("--rev", required=True, help="Git revision, e.g. HEAD~1")
    parser.add_argument(
        "--repo-path",
        required=True,
        help="Path inside the repo, e.g. data/Voting_Precincts.geojson",
    )
    parser.add_argument("--out", required=True, help="Destination file path")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path

    result = subprocess.run(
        ["git", "show", f"{args.rev}:{args.repo_path}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "git show failed")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.stdout, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
