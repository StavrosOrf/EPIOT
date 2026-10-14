# Troubleshooting

## Installation

```{dropdown} uv sync fails with "os error 396" or "os error 32"
:icon: alert

The repository is inside a OneDrive folder that locks files during upload. Keep the virtualenv
outside the synced tree with a junction, as described in {doc}`../getting-started/installation`.
`link-mode = "copy"` in `pyproject.toml` already avoids the hardlink error.
```

```{dropdown} "No such module: mod_spatialite" or "The specified module could not be found"
:icon: alert

SpatiaLite is not installed or not found.

- **Windows**: run `uv run python scripts/install_spatialite.py`, which unpacks the official bundle
  into `./.spatialite`. EPIOT prepends that folder to `PATH` automatically.
- **Linux**: `sudo apt-get install libsqlite3-mod-spatialite`.
- **macOS**: `brew install libspatialite`.
- Or set `SPATIALITE_LIBRARY_PATH` to the full path of the library.
```

```{dropdown} flask db upgrade errors on the first run
:icon: alert

On a fresh checkout the first upgrade may fail while SpatiaLite initialises its metadata. Run the
command a second time.
```

```{dropdown} The project .venv points to a Python that does not exist
:icon: alert

The virtualenv was created on another machine (for example, synced through OneDrive). Delete `.venv`
(or the junction target) and run `uv sync` again.
```

## Using the app

```{dropdown} No markers appear on the map
:icon: question

- Check that the area is covered by the data (currently Amsterdam).
- Zoom in: the map only allows zoom levels 14–16.
- Make sure the **Chargers** toggle is on.
- Open the browser console: a failing `/stations/within` request points to a database or SpatiaLite problem on the server.
```

```{dropdown} The load profile is flat zero
:icon: question

The selected day has no sessions for the chargers in the area. Check the session coverage:

`sqlite3 instance/default.sqlite "SELECT min(start), max(start) FROM sessions;"`

and pick a date in that range, or generate sessions for the missing days ({doc}`../operations/scheduled-updates`).
```

```{dropdown} "Load profiles are not available for this selection"
:icon: question

The backend failed for at least one area. Common causes:

- **Min. Charging Cost** is selected and the ReFlex service is unreachable from your network. Choose another strategy.
- The area contains no charging points.
- The server logged an exception: check the Flask console.
```

```{dropdown} Environment KPIs are empty or zero
:icon: question

There is no power-mix data for the selected range. Check `SELECT min(datetime), max(datetime) FROM power_mixes;`
and narrow the KPI range to those dates. Make sure the daily update runs and that
`ELECTRICITYMAPS_API_TOKEN` is set.
```

```{dropdown} The welcome dialog appears every time / never appears
:icon: question

It is shown until you tick **Don't show this again**, which is stored in the browser's `localStorage`.
Private windows and cleared site data reset it. Open it explicitly with **About** or by adding
`?landing` to the URL.
```

```{dropdown} "You can compare up to 3 areas"
:icon: question

Three areas are the maximum. Delete one with the trash tool before drawing another.
```

## Deployment

```{dropdown} 414 Request-URI Too Large / requests fail for big areas
:icon: alert

Charger IDs are passed in the query string. Start gunicorn with `--limit-request-line 18190` (or
larger) and raise `large_client_header_buffers` in nginx. See {doc}`../operations/deployment`.
```

```{dropdown} Icons are missing behind a proxy
:icon: alert

`/marker_icon` builds absolute URLs. Set `DEBUG = False` so that `ProxyFix` is active, and forward
`X-Forwarded-Proto`, `X-Forwarded-Host` (and `X-Forwarded-Prefix` for a sub-path) from the proxy.
```
