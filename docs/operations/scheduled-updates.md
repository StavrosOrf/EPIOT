# Scheduled updates

Two kinds of data age: **charging sessions** must exist for the dates users pick, and the
**power mix** must be fetched daily because the Electricity Maps history endpoint only covers the last
24 hours. `update_database.py` does both.

```{mermaid}
flowchart TB
    CRON([cron · daily 12:00]) --> SH[scripts/fetch_env_data.sh]
    SH --> PY[update_database.py]
    PY --> S1[Generate MC sessions<br/>100 days from today − 20]
    PY --> S2[Create tables if missing]
    PY --> S3[Fetch NL power mix<br/>last 24 h]
    S1 & S3 --> DB[(default.sqlite)]
    SH --> LOG[[logs/fetch.log]]
```

## What `update_database.py` does

1. Starts a minimal Flask app bound to the same database, with SpatiaLite loaded on connect.
2. Generates Monte Carlo sessions for **100 consecutive days starting 20 days ago**, using
   `load_daily_charging_sessions(..., method="MC", scope="NL")`.
3. Ensures all tables exist (`create_tables_if_not_exist`).
4. Fetches and upserts the latest power mix for `NL`.

:::{admonition} Re-running over days that already have sessions
:class: warning

The generator only checks whether a charger is still occupied **at midnight**; it does not check
sessions later in the day. Generating a day that already has sessions therefore **adds** a second set
on top of the first, and sessions on one charger can overlap. Because the job covers a 100-day window
every time it runs, a daily schedule regenerates the same days repeatedly.

Before scheduling it, either narrow the loop in `update_database.py` to days that have no sessions
yet (for example, start from the day after `max(sessions.start)`), or clear the affected days first.
:::

Run it by hand with:

```bash
uv run python update_database.py
```

## Scheduling with cron

`scripts/fetch_env_data.sh` activates the environment, sets `SPATIALITE_LIBRARY_PATH` and runs
`update_database.py`. Adjust the paths in the script to your server, then add a crontab entry
(`crontab -e`) to run it every day at noon:

```text
0 12 * * * /path/to/epiot/scripts/fetch_env_data.sh >> /path/to/epiot/logs/fetch.log 2>&1
```

:::{tip}
The shipped script activates a conda environment. On a uv-based install, replace the activation lines
with:

```bash
cd /path/to/epiot
export SPATIALITE_LIBRARY_PATH=mod_spatialite.so
uv run python update_database.py
```
:::

## Checking that updates work

```bash
# Latest stored power-mix hour and session coverage
sqlite3 instance/default.sqlite \
  "SELECT max(datetime) FROM power_mixes;
   SELECT min(start), max(start), count(*) FROM sessions;"

# Recent log output
tail -n 50 logs/fetch.log
```

If the power-mix timestamp stops advancing, environment KPIs for new dates will be empty; see
{doc}`../reference/troubleshooting`.
