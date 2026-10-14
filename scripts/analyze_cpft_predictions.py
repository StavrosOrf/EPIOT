"""Audit saved CPFT predictions without training or changing the application DB.

Run from the repository root:
    uv run --with openpyxl --with matplotlib python scripts/analyze_cpft_predictions.py

The input is a saved example export, not a new forecast for Amsterdam. Outputs
include independently recomputed metrics, baseline comparisons, a chart, and a
round-trip check of real exported forecasts in a disposable SQLite database.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_DIR = ROOT / "others/CPFT-main/CPFT-tool/CPFT_VS_Code_Python/outputs"


def regression_metrics(actual, predicted):
    actual, predicted = np.asarray(actual, float), np.asarray(predicted, float)
    if not (np.isfinite(actual).all() and np.isfinite(predicted).all()):
        raise ValueError("Missing/nonfinite evaluation data")
    error = predicted - actual
    variance = np.sum((actual - actual.mean()) ** 2)
    return dict(
        n=len(actual), mae=float(np.abs(error).mean()), rmse=float(np.sqrt(np.mean(error ** 2))),
        r2=float(1 - np.sum(error ** 2) / variance) if variance else None,
        mean_bias=float(error.mean()), actual_total_kwh=float(actual.sum()),
        predicted_total_kwh=float(predicted.sum()),
        total_bias_percent=float(100 * error.sum() / actual.sum()) if actual.sum() else None,
    )


def classification_metrics(actual, predicted, probability=None):
    actual, predicted = np.asarray(actual, int), np.asarray(predicted, int)
    if not (np.isin(actual, [0, 1]).all() and np.isin(predicted, [0, 1]).all()):
        raise ValueError("Occupancy labels must be binary")
    tp = int(((actual == 1) & (predicted == 1)).sum())
    tn = int(((actual == 0) & (predicted == 0)).sum())
    fp = int(((actual == 0) & (predicted == 1)).sum())
    fn = int(((actual == 1) & (predicted == 0)).sum())
    result = dict(
        n=len(actual), accuracy=float(np.mean(actual == predicted)),
        precision=tp / (tp + fp) if tp + fp else None,
        recall=tp / (tp + fn) if tp + fn else None,
        f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        true_positive=tp, true_negative=tn, false_positive=fp, false_negative=fn,
        observed_occupied_hours=int(actual.sum()), predicted_occupied_hours=int(predicted.sum()),
        observed_occupied_segments=int(np.sum(np.diff(np.r_[0, actual]) == 1)),
        predicted_occupied_segments=int(np.sum(np.diff(np.r_[0, predicted]) == 1)),
    )
    if probability is not None:
        probability = np.asarray(probability, float)
        if not (np.isfinite(probability).all() and ((probability >= 0) & (probability <= 1)).all()):
            raise ValueError("Invalid occupancy probabilities")
        positives, negatives = int(actual.sum()), int((1 - actual).sum())
        ranks = pd.Series(probability).rank(method="average").to_numpy()
        result["auc"] = float((ranks[actual == 1].sum() - positives * (positives + 1) / 2)
                              / (positives * negatives)) if positives and negatives else None
        result["brier_score"] = float(np.mean((probability - actual) ** 2))
    return result


def time_frame(frame):
    frame = frame.copy()
    # CPFT's Excel export strips timezone metadata from UTC timestamps.
    frame["hour"] = pd.to_datetime(frame["hour"], utc=True)
    if frame["hour"].duplicated().any():
        raise ValueError("Duplicate hourly timestamps")
    frame = frame.set_index("hour").sort_index()
    if not frame.index.to_series().diff().dropna().eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Gaps in hourly timeline")
    return frame


def compare_baselines(test, hourly, target, actual_col, predicted_col, classification=False):
    metrics = classification_metrics if classification else regression_metrics
    result = {"CPFT": metrics(test[actual_col], test[predicted_col])}
    for lag, label in [(1, "Last hour"), (24, "Previous day"), (168, "Previous week")]:
        # Join by timestamp on the whole history: no np.roll wraparound and no
        # dropping the first test observations for a baseline's convenience.
        values = hourly[target].reindex(test.index - pd.Timedelta(hours=lag)).to_numpy()
        if not np.isfinite(values).all():
            raise ValueError(f"Insufficient history for {label}")
        result[label] = metrics(test[actual_col], values)
    result["Always zero"] = metrics(test[actual_col], np.zeros(len(test)))
    return result


def raw_hourly_energy(csv_path, hourly_index):
    """Reconstruct unclipped hourly energy using the source's uniform allocation.

    This is a sensitivity check against session-derived labels, not meter data.
    Only required columns are read; user identifiers are not loaded or exported.
    """
    columns = ["connectionTime", "disconnectTime", "doneChargingTime", "kWhDelivered", "stationID", "timezone"]
    raw = pd.read_csv(csv_path, usecols=columns)
    for col in columns[:3]:
        raw[col] = pd.to_datetime(raw[col], errors="coerce", utc=True)
    raw["kWhDelivered"] = pd.to_numeric(raw["kWhDelivered"], errors="coerce")
    clean = raw.dropna(subset=["connectionTime", "disconnectTime", "kWhDelivered"])
    clean = clean[clean["disconnectTime"] > clean["connectionTime"]].copy()
    clean["charge_end"] = clean["doneChargingTime"].fillna(clean["disconnectTime"])
    starts = hourly_index.as_unit("ns").asi8
    step = 3_600_000_000_000
    energy = np.zeros(len(starts))
    occupancy = np.zeros(len(starts), dtype=int)
    for row in clean.itertuples():
        conn, disc, end = row.connectionTime.value, row.disconnectTime.value, row.charge_end.value
        occupancy[(starts < disc) & (starts + step > conn)] = 1
        if end > conn:
            overlap = np.maximum(0, np.minimum(starts + step, end) - np.maximum(starts, conn))
            energy += max(0, row.kWhDelivered) * overlap / (end - conn)
    return pd.DataFrame({"energy_kwh": energy, "occupied": occupancy}, index=hourly_index), dict(
        station_ids=sorted(raw.stationID.unique().tolist()),
        source_timezones=sorted(raw.timezone.unique().tolist()),
        raw_sessions=len(raw), usable_sessions=len(clean),
        first_connection=str(clean.connectionTime.min()), last_disconnect=str(clean.disconnectTime.max()),
    )


def exported_forecast_roundtrip(forecast, station_timezone):
    from sqlalchemy import create_engine, event
    from backend.cpft import ForecastBatch, adapt_cpft_output
    from backend.forecast_store import fetch_forecast_batch, save_forecast_batch
    from backend.models import ForecastHour, ForecastRun, ForecastSession

    tested = []
    with tempfile.TemporaryDirectory(prefix="epiot-saved-forecast-") as directory:
        engine = create_engine(f"sqlite:///{Path(directory).as_posix()}/audit.sqlite")

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        try:
            with engine.begin() as connection:
                # Audit-only numeric identity for source station 2-39-139-28.
                # This is not a mapping onto an Amsterdam station.
                connection.exec_driver_sql("CREATE TABLE charging_points (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql("INSERT INTO charging_points VALUES (1)")
                for model in (ForecastRun, ForecastHour, ForecastSession):
                    model.__table__.create(connection)
            for target, group in forecast.groupby(forecast.index.tz_convert(station_timezone).date):
                if len(group) != 24:
                    continue  # only complete local days in this September export
                point = adapt_cpft_output(1, group.reset_index().to_dict("records"),
                                          target_date=target, timezone_name=station_timezone)
                batch = ForecastBatch(
                    f"saved-example-{target}", target, station_timezone,
                    forecast.index[0].to_pydatetime(), "saved-example-export", (point,),
                )
                save_forecast_batch(engine, batch)
                save_forecast_batch(engine, batch)
                if fetch_forecast_batch(engine, batch.run_id) != batch:
                    raise AssertionError("Saved output changed in the database round trip")
                tested.append(dict(date=str(target), hours=len(point.hours), sessions=len(point.sessions),
                                   energy_kwh=sum(h.energy_kwh for h in point.hours)))
            with engine.connect() as connection:
                counts = {table: connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one()
                          for table in ["forecast_runs", "forecast_hourly", "forecast_sessions"]}
            assert counts["forecast_runs"] == len(tested)
            assert counts["forecast_hourly"] == sum(d["hours"] for d in tested)
        finally:
            engine.dispose()
    return dict(passed=True, complete_local_days=tested, row_counts_after_two_saves=counts,
                note="Temporary database; audit-only point ID; first forecast hour used as audit issue metadata, not a verified issue time.")


def database_status(database_path):
    with sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        forecast_tables = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'forecast_%'")]
        session = connection.execute("SELECT COUNT(*), MIN(start), MAX(start) FROM sessions").fetchone()
        return dict(forecast_tables=forecast_tables,
                    stations=connection.execute("SELECT COUNT(*) FROM columns").fetchone()[0],
                    charging_points=connection.execute("SELECT COUNT(*) FROM charging_points").fetchone()[0],
                    session_count=session[0], first_session_start=session[1], latest_session_start=session[2])


def draw_chart(stats, daily, future_blocks, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titlesize": 12, "figure.facecolor": "white", "axes.titleweight": "bold"})
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    models = ["CPFT", "Last hour", "Previous day", "Previous week"]
    positions = np.arange(len(models))
    colors = ["#1677a6", "#df8638"]
    for offset, metric, label, color in [(-.18, "accuracy", "Accuracy", colors[0]), (.18, "f1", "F1", colors[1])]:
        bars = axes[0, 0].bar(positions + offset, [stats["occupancy"][m][metric] for m in models], .34, label=label, color=color)
        axes[0, 0].bar_label(bars, fmt="%.3f", fontsize=9, padding=2)
    axes[0, 0].set(title="Occupancy: one-step test predictions", ylim=(0, 1.18), ylabel="Score (higher is better)")
    axes[0, 0].set_xticks(positions, models)
    axes[0, 0].legend(loc="upper left", ncols=2, frameon=False)
    for offset, metric, label, color in [(-.18, "mae", "MAE", colors[0]), (.18, "rmse", "RMSE", colors[1])]:
        bars = axes[0, 1].bar(positions + offset, [stats["energy"][m][metric] for m in models], .34, label=label, color=color)
        axes[0, 1].bar_label(bars, fmt="%.2f", fontsize=9, padding=2)
    axes[0, 1].set(title="Energy: one-step test predictions", ylabel="Error (kWh per hourly bin)", ylim=(0, 1.4))
    axes[0, 1].set_xticks(positions, models)
    axes[0, 1].legend(loc="upper left", frameon=False)
    axes[1, 0].plot(daily.index, daily.kWh_real, color="#354454", lw=1.3, label="Session-derived actual")
    axes[1, 0].plot(daily.index, daily.kWh_pred, color=colors[0], lw=1.2, label="CPFT")
    axes[1, 0].set(title="Daily totals of one-step predictions", ylabel="Energy (kWh per UTC day)")
    axes[1, 0].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    axes[1, 0].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    axes[1, 0].legend(frameon=False, fontsize=9)
    days = np.arange(7)
    axes[1, 1].bar(days - .18, [d["previous_week_kwh"] for d in future_blocks], .34,
                   color="#b6c1cc", label="Corresponding block last week")
    bars = axes[1, 1].bar(days + .18, [d["forecast_kwh"] for d in future_blocks], .34,
                         color=colors[0], label="Saved future forecast")
    axes[1, 1].bar_label(bars, fmt="%.2f", fontsize=8, padding=2)
    axes[1, 1].set(title="Seven-day forecast sanity check", ylabel="Energy (kWh per 24-hour block)")
    axes[1, 1].set_xticks(days, [str(i) for i in range(1, 8)])
    axes[1, 1].set_xlabel("Forecast day (blocks start at 03:00 UTC)")
    axes[1, 1].legend(frameon=False, fontsize=8)
    for ax in axes.flat:
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=.15)
    fig.suptitle("CPFT example station 2-39-139-28: saved prediction audit", fontsize=15, weight="bold")
    fig.supxlabel("2021 example data. Historical test scores are not day-ahead validation. Future ground truth is unavailable.", fontsize=10)
    fig.savefig(output / "prediction_diagnostics.png", dpi=180)
    fig.savefig(output / "prediction_diagnostics.svg")
    plt.close(fig)


def write_report(stats, output):
    o, e, f = stats["occupancy"], stats["energy"], stats["future"]
    change_direction = "below" if f["energy_change_from_previous_week_percent"] < 0 else "above"
    forecast_tables = ", ".join(stats["database"]["forecast_tables"]) or "none"
    lines = [
        "# CPFT prediction statistics", "",
        "The adapter and database path pass isolated correctness checks. Station-wide day-ahead predictions are not running or validated in the current app.", "",
        "## Available evidence", "",
        f"The saved export is for station {', '.join(stats['source_sessions']['station_ids'])}, with {o['CPFT']['n']:,} occupancy test hours and {e['CPFT']['n']:,} energy test hours in 2021. These are one-step predictions using observed input windows, not forecasts made once per day. No model was retrained or newly executed for this audit.", "",
        "The energy labels are reconstructed from session totals by uniform allocation over charging duration and then clipped using training-derived bounds. They are not direct hourly meter readings. Metrics below use the exported test labels, and baselines are joined by exact timestamp over the same test hours.", "",
        "## Recomputed test statistics", "",
        "| Method | Occupancy accuracy | Occupancy F1 | Energy MAE (kWh/hour bin) | Energy RMSE (kWh/hour bin) | Energy R² |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method in o:
        lines.append(f"| {method} | {o[method]['accuracy']:.2%} | {o[method]['f1']:.3f} | {e[method]['mae']:.3f} | {e[method]['rmse']:.3f} | {e[method]['r2']:.3f} |")
    lines += ["", f"CPFT occupancy precision is {o['CPFT']['precision']:.2%}, recall {o['CPFT']['recall']:.2%}, and AUC {o['CPFT']['auc']:.3f}. It misses {o['CPFT']['false_negative']} occupied hours and falsely predicts occupancy in {o['CPFT']['false_positive']} hours. It predicts {o['CPFT']['predicted_occupied_segments']} occupied segments versus {o['CPFT']['observed_occupied_segments']} observed hourly segments; these segments are not exact sessions.", "",
        f"CPFT predicts {e['CPFT']['predicted_total_kwh']:.2f} kWh against {e['CPFT']['actual_total_kwh']:.2f} kWh in the energy test set, a total bias of {e['CPFT']['total_bias_percent']:.2f}%. Compared with last-hour persistence, MAE improves by {100*(1-e['CPFT']['mae']/e['Last hour']['mae']):.2f}% and RMSE by {100*(1-e['CPFT']['rmse']/e['Last hour']['rmse']):.2f}%. Occupancy accuracy and F1 are both worse than last-hour persistence.", "",
        f"The raw-session reconstruction differs from the clipped test energy labels in {stats['unclipped_sensitivity']['changed_test_bins']} hourly bins. Against those unclipped reconstructed labels, CPFT energy MAE is {stats['unclipped_sensitivity']['cpft']['mae']:.3f} and RMSE is {stats['unclipped_sensitivity']['cpft']['rmse']:.3f} kWh. This is a label sensitivity check, not an independent metered evaluation.", "",
        "## Saved future forecast", "",
        f"The saved forecast covers {f['start']} through {f['end_exclusive']} (exclusive): {f['hours']} hours. It predicts {f['occupied_hours']} occupied hours ({f['occupancy_rate']:.2%}) and {f['energy_kwh']:.3f} kWh in total. The corresponding preceding week contains {f['previous_week_occupied_hours']} occupied hours and {f['previous_week_energy_kwh']:.3f} kWh. Forecast energy is {abs(f['energy_change_from_previous_week_percent']):.2f}% {change_direction} that historical total.", "",
        "This collapse is a diagnostic flag, not a measured future error: the supplied observations end before this forecast period. MAE/RMSE for the future forecast and exact session arrival/departure accuracy are unavailable.", "",
        "## Integration and database checks", "",
        f"The application database contains {stats['database']['stations']:,} stations and {stats['database']['charging_points']:,} charging points. Forecast tables present: {forecast_tables}. Its latest session start is {stats['database']['latest_session_start']}. No application data were written.", "",
        f"Real saved CPFT outputs for {len(stats['roundtrip']['complete_local_days'])} complete days in {stats['source_sessions']['source_timezones'][0]} were validated, saved twice, and fetched unchanged from a temporary SQLite database. Final row counts: {stats['roundtrip']['row_counts_after_two_saves']}. The numeric point identity was created only for this audit and was not mapped to an Amsterdam station. The first forecast timestamp served only as round-trip issue metadata; the export does not provide a verified issue timestamp.", "",
        f"Current automated-suite results: {stats.get('tests', 'not supplied')}. The automated model calls are stubbed; the additional round-trip check here uses actual saved CPFT outputs.", "",
        "## Required before trusting daily predictions", "",
        "1. Connect trained CPFT models and fitted preprocessing artifacts to the app, with fresh observed histories and explicit station mapping.",
        "2. Correct the recursive feature updates: nonconsecutive lag offsets are shifted as adjacent columns, standardized energy/occupancy inputs receive raw values, and several calendar/rolling/cross-target features are held constant. These are source-level findings in CPFT_pipeline_VS_Code_Python.py (lines 720-727, 854-857, 1039-1065). Their exact contribution to the low forecast has not been measured.",
        "3. Run rolling day-ahead backtests with a fixed issue time and only observations available then; compare all forecast leads with day/week baselines across representative stations. The current one-step test scores cannot certify day-ahead performance.",
        "4. Evaluate derived-session timing and flexibility separately: hourly occupied segments cannot uniquely identify individual sessions.", "",
        "![Prediction diagnostics](prediction_diagnostics.png)", "",
        "## Reproduction and sources", "",
        "Run `uv run --with openpyxl --with matplotlib python scripts/analyze_cpft_predictions.py` from the repository root. Optionally pass `--test-results <pytest-junit.xml>` to include an executed test summary.", "",
        f"Source workbook: `{stats['source_workbook']}`. SHA-256: `{stats['source_sha256']}`.", "",
        "Sheets: hourly_input, metrics_summary, test_availability, test_kwh, forecast_whole_period. The source CSV is Station_2_39_139_28.csv. Detailed numbers, periods, reconciliation checks, and library versions are in statistics.json. The original workbook and CSV are unchanged.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_DIR / "EV_forecasting_upgraded_results.xlsx")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/cpft_prediction_statistics")
    parser.add_argument("--test-results", type=Path)
    args = parser.parse_args()
    args.source = args.source.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    sheets = pd.read_excel(args.source, sheet_name=["hourly_input", "metrics_summary", "test_availability", "test_kwh", "forecast_whole_period"])
    hourly, avail, energy, forecast = [time_frame(sheets[name]) for name in
                                      ["hourly_input", "test_availability", "test_kwh", "forecast_whole_period"]]
    assert forecast.index.min() > hourly.index.max()
    assert np.array_equal(avail.availability_real, hourly.loc[avail.index, "availability"])
    assert np.allclose(energy.kWh_real, hourly.loc[energy.index, "kWhDelivered"], atol=1e-6)
    occupancy = compare_baselines(avail, hourly, "availability", "availability_real", "availability_pred_bin", True)
    occupancy["CPFT"] = classification_metrics(avail.availability_real, avail.availability_pred_bin, avail.availability_pred_prob_for_auc)
    energy_stats = compare_baselines(energy, hourly, "kWhDelivered", "kWh_real", "kWh_pred")
    reported = sheets["metrics_summary"].iloc[0]
    reconciled = dict(
        occupancy_f1=np.isclose(occupancy["CPFT"]["f1"], reported.availability_test_f1),
        occupancy_auc=np.isclose(occupancy["CPFT"]["auc"], reported.availability_test_auc),
        energy_mae=np.isclose(energy_stats["CPFT"]["mae"], reported.kWh_test_mae),
        energy_rmse=np.isclose(energy_stats["CPFT"]["rmse"], reported.kWh_test_rmse),
    )
    if not all(reconciled.values()):
        raise AssertionError("Recomputed metrics do not reconcile with the saved summary")
    raw_hourly, source_sessions = raw_hourly_energy(ROOT / "others/CPFT-main/CPFT-tool/Station_2_39_139_28.csv", hourly.index)
    assert np.array_equal(raw_hourly.occupied, hourly.availability)
    raw_actual = raw_hourly.loc[energy.index, "energy_kwh"].to_numpy()
    previous_week = hourly.reindex(forecast.index - pd.Timedelta(days=7))
    if previous_week.isna().any().any():
        raise ValueError("Previous-week context is incomplete")
    future_energy = forecast.kWh_forecast_next_whole_period
    if not ((np.isfinite(future_energy) & (future_energy >= 0)).all()
            and forecast.loc[forecast.availability_forecast_bin == 0, "kWh_forecast_next_whole_period"].eq(0).all()):
        raise ValueError("Future forecast violates energy/occupancy consistency")
    blocks = [dict(day=i+1, forecast_kwh=float(future_energy.iloc[i*24:(i+1)*24].sum()),
                   previous_week_kwh=float(previous_week.kWhDelivered.iloc[i*24:(i+1)*24].sum())) for i in range(7)]
    daily_counts = energy.kWh_real.resample("D").count()
    daily = energy.resample("D").sum().loc[daily_counts.eq(24)]
    stats = dict(
        analyzed_at_utc=datetime.now(timezone.utc).isoformat(),
        source_workbook=(args.source.relative_to(ROOT).as_posix() if args.source.is_relative_to(ROOT) else str(args.source)),
        source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
        source_sessions=source_sessions,
        library_versions={p: importlib.metadata.version(p) for p in ["numpy", "pandas", "openpyxl", "matplotlib", "sqlalchemy", "geoalchemy2"]},
        occupancy=occupancy, energy=energy_stats,
        test_periods=dict(occupancy_start=str(avail.index.min()), occupancy_end=str(avail.index.max()),
                          energy_start=str(energy.index.min()), energy_end=str(energy.index.max())),
        daily_totals_of_one_step_predictions=regression_metrics(daily.kWh_real, daily.kWh_pred),
        reported_metrics_reconciled={k: bool(v) for k,v in reconciled.items()},
        unclipped_sensitivity=dict(changed_test_bins=int((np.abs(raw_actual-energy.kWh_real)>1e-5).sum()),
                                  cpft=regression_metrics(raw_actual, energy.kWh_pred)),
        future=dict(start=str(forecast.index.min()), end_exclusive=str(forecast.index.max()+pd.Timedelta(hours=1)),
                    hours=len(forecast), occupied_hours=int(forecast.availability_forecast_bin.sum()),
                    occupancy_rate=float(forecast.availability_forecast_bin.mean()), energy_kwh=float(future_energy.sum()),
                    previous_week_energy_kwh=float(previous_week.kWhDelivered.sum()),
                    previous_week_occupied_hours=int(previous_week.availability.sum()),
                    energy_change_from_previous_week_percent=float(100*(future_energy.sum()/previous_week.kWhDelivered.sum()-1)),
                    ground_truth_available=False, blocks=blocks),
        database=database_status(ROOT / "instance/default.sqlite"),
        roundtrip=exported_forecast_roundtrip(forecast, source_sessions["source_timezones"][0]),
    )
    if args.test_results:
        suites = ET.parse(args.test_results).getroot().iter("testsuite")
        totals = {key: 0 for key in ["tests", "failures", "errors", "skipped"]}
        for suite in suites:
            for key in totals:
                totals[key] += int(suite.get(key, "0"))
        stats["tests"] = totals
    (args.output / "statistics.json").write_text(json.dumps(stats, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    draw_chart(stats, daily, blocks, args.output)
    write_report(stats, args.output)
    print(json.dumps({"occupancy": occupancy["CPFT"], "energy": energy_stats["CPFT"],
                      "future": stats["future"], "roundtrip": stats["roundtrip"]}, indent=2))
    print(f"Report: {args.output / 'report.md'}")


if __name__ == "__main__":
    main()
