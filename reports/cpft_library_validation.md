# CPFT library validation

Library built 2026-10-14T21:48:31+00:00 (inputs `de5b92aeaae6ef1c`). 300 random points per date, 60% inside the Amsterdam atlas, mixed power and 20% fast; base demand. Exact = the checkpoints run on each point's own 14-day history and power. Library = 5 independent draws per point, averaged.

| Date | Day | Hours | Occupied h/point, exact | Library | s.e. | z | kWh/point, exact | Library | Mean abs. hourly occupancy diff. |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025-02-13 | Thu | 30 | 15.76 | 14.90 | 1.26 | -0.69 | 2.18 | 2.05 | 0.029 |
| 2025-03-15 | Sat | 30 | 13.51 | 12.12 | 1.29 | -1.07 | 1.51 | 1.39 | 0.046 |
| 2025-03-27 | Thu | 30 | 13.69 | 14.67 | 1.34 | +0.73 | 1.81 | 1.79 | 0.033 |
| 2026-01-22 | Thu | 30 | 13.85 | 13.09 | 1.24 | -0.61 | 2.28 | 2.23 | 0.026 |
| 2026-05-31 | Sun | 30 | 16.97 | 17.87 | 1.19 | +0.76 | 3.28 | 3.13 | 0.033 |
| 2026-06-20 | Sat | 30 | 15.68 | 15.76 | 1.16 | +0.07 | 3.54 | 3.83 | 0.017 |
| 2026-08-18 | Tue | 30 | 15.15 | 14.34 | 1.16 | -0.70 | 5.02 | 4.77 | 0.027 |
| 2026-09-15 | Tue | 30 | 15.97 | 15.16 | 1.17 | -0.69 | 5.23 | 4.96 | 0.031 |
| 2027-01-03 | Sun | 30 | 14.24 | 12.62 | 1.27 | -1.28 | 1.90 | 1.62 | 0.054 |
| 2027-01-11 | Mon | 30 | 15.97 | 16.62 | 1.27 | +0.51 | 1.90 | 2.72 | 0.022 |
| 2027-02-02 | Tue | 30 | 15.17 | 14.27 | 1.33 | -0.68 | 1.63 | 1.61 | 0.030 |
| 2027-09-07 | Tue | 30 | 15.74 | 14.76 | 1.15 | -0.85 | 5.65 | 5.20 | 0.035 |

Across dates: 15.14 occupied hours per point exactly, 14.68 from the library; chi-square 7.2 on 12 degrees of freedom (p = 0.846).

The standard error combines the exact runs' sampling error with the library's: each cell's finite
trajectories are shared by every point that uses it on that day, so a cell's mean error is common to
those points. A small p-value would indicate an approximation beyond this sampling error.
