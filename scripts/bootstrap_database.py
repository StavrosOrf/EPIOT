"""Initialize EPIOT offline from the committed compact country snapshots."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.bootstrap_data import SEED_DIR, bootstrap


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT/"instance/default.sqlite")
    parser.add_argument("--seed-dir", type=Path, default=SEED_DIR)
    parser.add_argument("--data-dir", type=Path, default=ROOT/"data")
    parser.add_argument("--countries", nargs="+", help="ISO codes, e.g. NL DE FR (default: all countries)")
    args = parser.parse_args(argv)
    try:
        result = bootstrap(args.database, seed_dir=args.seed_dir, data_dir=args.data_dir, countries=args.countries)
    except (ValueError, FileExistsError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
