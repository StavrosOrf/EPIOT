"""Export the working database and required inputs into small GitHub-ready files."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.bootstrap_data import SEED_DIR, export_snapshots


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT/"instance/default.sqlite")
    parser.add_argument("--output", type=Path, default=SEED_DIR)
    parser.add_argument("--data-dir", type=Path, default=ROOT/"data")
    args = parser.parse_args()
    manifest = export_snapshots(args.database, args.output, args.data_dir)
    print(json.dumps({code: dict(bytes=item["bytes"], **item["tables"]) for code, item in manifest["countries"].items()}, indent=2))
