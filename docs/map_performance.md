# Map performance checks

Run the repeatable comparison against the pre-optimization Git revision:

```powershell
uv run python scripts/benchmark_map.py --browser --repeats 5
```

The default database is `instance/default.sqlite`, opened with SQLite `mode=ro`.
Supply `--database <path>` to compare a different installation or a disposable
fixture. Imports and operating-system disk caches are warm, but each before/after
zoom sequence starts with empty server overview caches and a fresh browser page.
The script rejects a run if the database or WAL changes during measurement.
It does not change the checkout or application data.

The benchmark uses the original density implementation and map loader from
`4ba8f16`, alternating old/new execution order. It discards one warmup, saves every
timing sample, and checks exact cell counts and representative locations. Source
hashes and database stamps identify the measured inputs. Results are written to
`reports/map_speed_comparison.json` and `.md`.

`--browser` starts an isolated headless Chrome profile and uses the application's
Leaflet 1.9.4 and MarkerCluster 1.5.3 libraries. They are downloaded once into
`.tmp/map-benchmark/vendor` before timing. Set `--chrome <executable>` if Chrome
is elsewhere. Node.js 20 or newer is required. Browser measurements include local
HTTP, JSON parsing, clustering, DOM updates and two animation frames; they exclude
basemap downloads and zoom animation. The report includes request counts, marker
creation counts and long tasks. It shows both first-use and repeat-use timings;
the two paint frames can dominate very small repeat-use costs.

Omit `--browser` for the server-only comparison. If the default uv cache is
inaccessible and the environment is installed, use
`uv run --locked --no-sync --cache-dir .cache/uv ...`.

Regression checks:

```powershell
uv run pytest tests/test_map_density.py tests/test_charger_sources.py -q
node --preserve-symlinks --preserve-symlinks-main --test tests/test_map_density.mjs
```

These cover aggregation at every overview zoom, floating-point ties, cold/warm
equivalence, concurrent cache building, database/WAL changes, application
isolation, stale responses, request coalescing, bounded cache expiry, marker
reuse and incremental rendering. A small executable comparison runs against a
temporary database. No test asserts a hardware-dependent speed ratio.

The overview cache holds one location snapshot plus at most nine zoom summaries
per application. Browser caching is bounded to 16 views for 30 seconds. For an
in-memory database, explicitly change `ANALYSIS_DATA_REVISION` after writes.
The city-level cluster insertion uses Leaflet's documented
[chunked loading options](https://github.com/Leaflet/Leaflet.markercluster#chunked-addlayers-options).
