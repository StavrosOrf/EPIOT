"""Download open charger-location data and load it into the EPIOT database.

    uv run python scripts/update_charger_data.py                 # fetch + import all
    uv run python scripts/update_charger_data.py --skip-fetch    # re-import local files
    uv run python scripts/update_charger_data.py --sources ndw osm

Raw files go to instance/chargers/raw/, provenance to instance/chargers/manifest.json.
Run `uv run flask --app app db upgrade` once first. See docs/charger_sources.md.
"""

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoalchemy2 import load_spatialite  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402

from backend.charger_import import import_source, pilot_area, region_counts  # noqa: E402
from backend.charger_positions import Geocoder, repair_positions  # noqa: E402
from backend.charger_sources import READERS, SOURCES, fetch, load_manifest, save_manifest  # noqa: E402
from backend.spatial_profiles import DEFAULT_ATLAS  # noqa: E402
from backend.spatialite import configure_spatialite  # noqa: E402


def engine_for(path):
    configure_spatialite()
    engine = create_engine(f"sqlite:///{Path(path).resolve().as_posix()}")
    event.listen(engine, "connect", lambda connection, _: load_spatialite(connection))
    return engine


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", nargs="+", choices=list(SOURCES), default=list(SOURCES))
    parser.add_argument("--skip-fetch", action="store_true", help="import the files already in instance/chargers/raw")
    parser.add_argument("--skip-import", action="store_true", help="only download")
    parser.add_argument("--database", default=ROOT / "instance/default.sqlite")
    parser.add_argument("--dedupe-metres", type=float, default=30.,
                        help="skip sites this close to an Amsterdam pilot charger (0 disables)")
    parser.add_argument("--no-geocode", action="store_true",
                        help="repair positions offline only (swaps); skip address lookups")
    parser.add_argument("--include-pilot-area", action="store_true",
                        help="also import NDW sites inside Amsterdam, next to the pilot chargers")
    args = parser.parse_args()

    if not args.skip_fetch:
        fetch(args.sources)
    if args.skip_import:
        return

    engine = engine_for(args.database)
    manifest = load_manifest()
    # Inside Amsterdam the pilot chargers (with observed sessions and grid
    # links) stand in for NDW, so selections there are not counted twice
    amsterdam = None if args.include_pilot_area else pilot_area(DEFAULT_ATLAS)
    geocoder = None if args.no_geocode else Geocoder()
    for source in args.sources:
        started = time.perf_counter()
        print(f"Importing {SOURCES[source].label}")
        try:
            sites, fixes = repair_positions(READERS[source](), geocoder)
            if any(value for key, value in fixes.items() if key != "geocoder_requests"):
                print("  positions: " + ", ".join(f"{key.replace('_', ' ')} {value:,}" for key, value in fixes.items()))
            with engine.begin() as connection:
                stats = import_source(connection, source, sites, dedupe_metres=args.dedupe_metres,
                                      exclude=amsterdam if source == "ndw" else None,
                                      countries=SOURCES[source].countries)
        except FileNotFoundError as exc:
            print(f"  skipped: {exc.filename} is missing; run without --skip-fetch")
            continue
        manifest.setdefault("imports", {})[source] = dict(stats, positions=fixes)
        print(f"  {stats['sites']:,} sites, {stats['points']:,} charging points; skipped "
              f"{stats['skipped_pilot_area']:,} in the pilot area, {stats['skipped_pilot_duplicates']:,} near "
              f"pilot chargers, {stats['skipped_repeated_sites']:,} repeated, "
              f"{stats['skipped_bad_position']:,} misplaced, {stats['skipped_outside_coverage']:,} abroad "
              f"({time.perf_counter()-started:.0f} s)")
    with engine.connect() as connection:
        manifest["regions"] = region_counts(connection)
    save_manifest(manifest)
    for region, counts in manifest["regions"].items():
        print(f"  {region:<12} {counts['sites']:>7,} sites {counts['points']:>8,} points")


if __name__ == "__main__":
    main()
