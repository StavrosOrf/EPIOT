# Environmental scenario KPIs

The application compares AFAP, ALAP, average-power and minimum-carbon schedules
using identical sessions and daily delivered-energy budgets. Each day counts the
sessions that **arrive** that day and charges them from their true arrival; a
connection still running at midnight keeps its average-power share up to
midnight. Connections that arrived the evening before belong to the previous
day, so no schedule restarts charging at 00:00. Load profiles go further and
follow every connection to its real departure, cropping only at the window
edges, so AFAP/ALAP energy inside the window can differ for connections that
cross its edges. Results are
**estimated scenario footprints**, not verified local emissions or demonstrated
avoided emissions. The source selector and date range apply to the calculation.

## Free data and historical reference

The canonical grid pipeline has **no network requests, credentials or paid API
dependency**. It reads the existing Dutch `power_mixes` data and, optionally, a
free/local hourly CSV. The current application database contains 72 original
hourly values across six days in 2025. Their original provider-estimation flags
were not retained and are recorded as unknown.

Exact-date observations take priority. For otherwise missing values, the default
uses the **latest complete 24-hour original profile**, indexed by local hour in
Europe/Amsterdam. Every borrowed value stores its original source timestamp and
has `is_stale=true` and `is_estimated=true`. Repeated DST hours reuse the same
local-hour reference; absent hours are not inserted into a 23-hour day. A partial
profile cannot silently become a complete reference.

This does not recreate the actual grid mix for unobserved dates. The UI names the
reference period and distinguishes energy covered by a reference from energy
covered by data on matching dates. The initial reference is 22–23 October 2025.
Missing values remain null whenever no valid reference exists or stale fallback
is disabled. A real zero carbon intensity or renewable share is preserved.

Imported original observations are stored in `instance/grid_data.sqlite`, with
UTC interval-start timestamps, independent carbon/renewable quality flags,
provider/source information and original source timestamps. Every request
resolves its own window from them (and from legacy `power_mixes` rows) on the
fly, so there is nothing to prepare or refresh on a schedule, and new
observations are used by the next request. Writes are atomic and use SQLite WAL;
the main application database is opened read-only by the importer.

```bash
uv run python scripts/prepare_grid_data.py --csv /path/to/free-NL-hourly.csv
uv run python scripts/prepare_grid_data.py --start 2026-10-08 --end 2026-10-14 --no-stale
```

Run the importer once when a new dataset is available. It copies the legacy
`power_mixes` rows and the CSV into the observation store, then prints how the
given range would resolve (matching-date, reference and missing hours).

CSV required columns are `timestamp`, `co2_intensity` (gCO2e/kWh) and
`renewable_percentage` (0–100). Timestamps must be aware hourly interval starts,
for example `2025-10-22T00:00:00Z`. Optional columns are `zone` (NL only),
`carbon_is_estimated`, `renewable_is_estimated` (or shared `is_estimated`),
`source` and `basis`. Empty or invalid metric values become null; duplicate
timestamps and ambiguous timezone-free timestamps are rejected. Supply
consumption-based data when available; unspecified basis is recorded as unknown.

Flask settings are `GRID_DATA_CACHE` (the observation store) and `GRID_ALLOW_STALE`
(use `FLASK_` prefixes for environment configuration). For strict matching-date
calculations set `FLASK_GRID_ALLOW_STALE=false`. The importer accepts
`--database`, `--cache`, `--csv` and `--timezone`; `EPIOT_GRID_CSV` sets a
default CSV. No paid or live feed is called.

## Accounting and coverage

For each 10-minute interval, energy is power in kW divided by six. Emissions are
`sum(energy_kwh * carbon_intensity) / 1000` in kgCO2e. Mean intensity is
energy-weighted. Renewable share is `sum(energy * renewable_percentage) /
sum(covered_energy)`. Carbon and renewable coverage are independent.

Summary metrics include delivered kWh, covered emissions, mean gCO2e/kWh,
renewable share, carbon/renewable energy coverage, matching-date energy coverage,
estimated-data percentage and complete/partial/reference status. A reference can
cover 100% of energy while matching-date coverage is 0%. Partial emissions are
not extrapolated to the full range. Differences against AFAP are reported only
when both carbon footprints are fully covered and delivered energy is equal.
All metrics and provenance are also included in the downloaded KPI workbook.

## Feasible minimum-carbon charging

Boundary connections contribute their uniform-charging energy share within each
local day. AFAP, ALAP, average and minimum-carbon schedules all receive that
same budget. Full connection duration remains available for session statistics.
The same daily-budget rule is used by the load/flexibility endpoint, including
23/25-hour days.

Minimum carbon fills the lowest-intensity feasible 10-minute intervals first,
with exact fractional-interval capacity, charger power and connection limits.
Charging may pause. This solves the separable linear objective for non-overlapping
single-plug sessions. It imposes daily energy quotas, has no feeder/network model,
and does not model charging losses. It is a historical/reference scenario optimum,
not a claim of operational forecast accuracy or causal avoided emissions.

Every candidate charging interval needs carbon data. Missing carbon values or
overlapping connections make minimum-carbon scheduling explicitly unavailable;
the application never silently switches to AFAP or zero carbon. Renewable-data
gaps can make renewable metrics partial without invalidating a carbon optimum.

Verification includes comparison with independent linear-program solutions,
fixed energy and power bounds, overnight/window boundaries, DST, missing signals,
stale provenance, read-only preparation, partial accounting and API consistency.
