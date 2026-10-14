# Charger map speed comparison

Baseline `4ba8f161c14b39bd95fcb033df9abd3ea0c715d0`; 586,291 charging points; 5 measured repeats after one discarded warmup.

Database opened read-only. Server caches reset before each zoom sequence; imports and OS disk cache are warm.
When enabled, browser cases use real headless Chrome, Leaflet 1.9.4 and MarkerCluster 1.5.3 at 1280 x 800.
They include local HTTP, JSON parsing, clustering, DOM updates and two paint frames. Basemap tiles and zoom animation are excluded.
All returned cells and displayed charger counts/locations are checked against the original implementation.

| Comparison | Before median (ms) | After median (ms) | Speedup |
|---|---:|---:|---:|
| Server: First city overview (empty server cache) | 1638.08 | 856.13 | 1.91x |
| Server: First visit to next zoom | 1296.66 | 83.23 | 15.58x |
| Server: First country overview | 980.50 | 36.97 | 26.53x |
| Server: First Europe overview | 917.23 | 26.78 | 34.26x |
| Server: Return to city overview | 1.96 | 2.29 | 0.85x |
| Browser: First zoom out to city overview | 1693.80 | 890.50 | 1.90x |
| Browser: First visit to next zoom | 1310.40 | 127.60 | 10.27x |
| Browser: First country overview | 965.10 | 66.00 | 14.62x |
| Browser: First Europe overview | 966.10 | 65.60 | 14.73x |
| Browser: Return to city overview | 32.80 | 33.60 | 0.98x |
| Browser: Repeat unchanged viewport | 33.60 | 32.60 | 1.03x |
| Browser: Small pan at city overview | 32.60 | 32.70 | 1.00x |

## Browser work per action

| Action | Requests before / after | New markers before / after |
|---|---:|---:|
| Browser: First zoom out to city overview | 1 / 1 | 166 / 166 |
| Browser: First visit to next zoom | 1 / 1 | 154 / 154 |
| Browser: First country overview | 1 / 1 | 139 / 139 |
| Browser: First Europe overview | 1 / 1 | 22 / 22 |
| Browser: Return to city overview | 1 / 0 | 166 / 166 |
| Browser: Repeat unchanged viewport | 1 / 0 | 166 / 0 |
| Browser: Small pan at city overview | 1 / 1 | 165 / 1 |

These timings describe this dataset and machine, not remote production latency. Speedups are not multiplied together or enforced in tests.
Browser viewport cache lifetime is 30 seconds and capacity is 16 views. Server snapshots invalidate on database/WAL/manifest changes.
Raw samples, browser version, data stamps and source hashes are in the adjacent JSON file.
