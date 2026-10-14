# Analysis speed comparison

Baseline: `4ba8f161c14b39bd95fcb033df9abd3ea0c715d0`; 5 measured repeats after one discarded warmup.

Synthetic fixtures on this machine; local single-worker HTTP, SQLite and real SpatiaLite.
No added network delay. HTTP timings include requests and JSON parsing, but exclude plotting/DOM rendering.
Cold means an empty scenario cache, with Python imports and the atlas already loaded.
CPFT inference and external cost optimization are not benchmarked.

| Comparison | Before median (ms) | After median (ms) | Speedup | Time reduction |
|---|---:|---:|---:|---:|
| Warm cache reads: 1000 points | 1405.306 | 6.430 | 218.56x | 99.5% |
| Cold simple scenario: 100 points, 1 day | 992.595 | 860.302 | 1.15x | 13.3% |
| Warm simple scenario: 100 points, 1 day | 142.525 | 3.961 | 35.98x | 97.2% |
| Cold spatial scenario: 100 points, 1 day | 1162.206 | 978.726 | 1.19x | 15.8% |
| Warm spatial scenario: 100 points, 1 day | 278.550 | 5.695 | 48.91x | 98.0% |
| Basic KPI computation: 100 points x 7 days | 393.377 | 147.744 | 2.66x | 62.4% |
| Basic KPI computation: 500 points x 30 days | 8277.576 | 3034.000 | 2.73x | 63.3% |
| HTTP first load (warm server cache) | 157.762 | 24.797 | 6.36x | 84.3% |
| HTTP switch Load to Flexibility | 157.944 | 5.472 | 28.86x | 96.5% |
| HTTP change charging strategy | 162.681 | 20.838 | 7.81x | 87.2% |
| HTTP first basic KPIs | 1243.181 | 118.171 | 10.52x | 90.5% |
| HTTP open Environment after basic KPIs | 0.001 | 153.695 | Deferred work | n/a |
| HTTP full KPI workflow (basic + Environment) | 1243.182 | 272.629 | 4.56x | 78.1% |

The environmental follow-up defers work: inspect the full-KPI-workflow row as well as time to basic KPIs.
The microbenchmarks isolate individual changes and their speedups must not be multiplied together.
Wall-clock speed is recorded, not asserted in CI. Correctness and request/connection counts are asserted.

Raw samples, fixture settings, request counts, payload sizes and source hashes are in the adjacent JSON file.

## HTTP work per action

| Action | Before requests / bytes | After requests / bytes |
|---|---:|---:|
| HTTP first load (warm server cache) | 3 / 50094 | 3 / 22107 |
| HTTP switch Load to Flexibility | 3 / 50094 | 1 / 84 |
| HTTP change charging strategy | 3 / 46822 | 2 / 18533 |
| HTTP first basic KPIs | 3 / 40862 | 2 / 5586 |
| HTTP open Environment after basic KPIs | 0 / 0 | 2 / 7300 |
| HTTP full KPI workflow (basic + Environment) | 3 / 40862 | 4 / 12886 |
