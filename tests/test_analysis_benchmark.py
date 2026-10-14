"""Opt-in real timing comparison; never enforce machine-dependent speed ratios."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.environ.get("EPIOT_BENCHMARK") != "1",
                    reason="Set EPIOT_BENCHMARK=1 to run the local HTTP/SQLite speed comparison")
def test_before_after_analysis_benchmark(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path/"speed.json"
    completed = subprocess.run([sys.executable, str(root/"scripts/benchmark_analysis.py"),
        "--repeats", "2", "--points", "10", "--days", "2", "--cache-points", "100",
        "--kpi-points", "20", "--kpi-days", "3", "--output", str(output)],
        cwd=root, text=True, capture_output=True, timeout=180)
    assert completed.returncode == 0, completed.stdout+"\n"+completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["shared_numerical_dependencies_verified"]
    assert report["baseline_commit"].startswith("4ba8f16")
    assert len(report["results"]) == 13
    for row in report["results"]:
        for variant in ("before", "after"):
            assert len(row[variant]["samples_ms"]) == 2
            assert 0 < row[variant]["min_ms"] <= row[variant]["median_ms"] <= row[variant]["max_ms"]
    switch = next(row for row in report["http_actions"] if row["name"] == "HTTP switch Load to Flexibility")
    assert switch["before_requests"] == 3
    assert switch["after_paths"] == ["/stations/analysis-version"]
    assert switch["after_bytes"] < switch["before_bytes"]
    assert output.with_suffix(".md").exists()
