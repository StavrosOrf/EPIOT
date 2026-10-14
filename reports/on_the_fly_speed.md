# On-request scenario speed

Baseline: `9ef972c` (scenario cache filled by a daily job; CPFT inference on a cache miss). After: the working tree. Median of 3 repeats after one discarded warm-up, on AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD.

Timings cover scenario generation plus the load profile or KPI calculation, in process.
They exclude imports, loading the CPFT model/library and the atlas, HTTP and the database.
**Before, cold** is a day the daily job had not prepared (a new date, seed or demand level);
**before, warm** reads the prepared cache. **After** has no cache: every request is generated.

| Case | Before, cold (ms) | Before, warm (ms) | After (ms) | vs cold | vs warm |
|---|---:|---:|---:|---:|---:|
| Load profile, simple, 1000 points | 8,273 | 86 | 43 | 191x | 2.0x |
| Load profile, spatial, 1000 points | 8,354 | 102 | 54 | 154x | 1.9x |
| Load profile, CPFT, 64 points | 6,137 | 11 | 3 | 1,780x | 3.2x |
| Basic KPIs, spatial, 500 points x 7 days | 29,656 | 510 | 53 | 563x | 9.7x |
| Environment KPIs, simple, 500 points x 7 days | 29,381 | 588 | 66 | 447x | 9.0x |
| Basic KPIs, CPFT, 64 points x 3 days | 18,191 | 33 | 11 | 1,732x | 3.2x |

Session counts (before / after), as a check of comparable scenario volumes:

- Load profile, simple, 1000 points: 2,772 / 2,824
- Load profile, spatial, 1000 points: 3,075 / 2,994
- Load profile, CPFT, 64 points: 146 / 135
- Basic KPIs, spatial, 500 points x 7 days: 4,623 / 4,292
- Basic KPIs, CPFT, 64 points x 3 days: 47 / 40

Raw samples are in the adjacent JSON file.
