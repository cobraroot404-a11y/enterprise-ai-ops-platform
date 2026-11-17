# REL-01 start/stop cycles (2026-11-13)

`python scripts/rel01_start_cycles.py --cycles 12`: 12 of 12 cycles started every service and stopped cleanly; 0 failed.

| Cycle | Start | `up` exit | `up` seconds | `down` exit | `down` seconds |
|---|---|---|---|---|---|
| 1 | 14:30:53 | 0 | 25.0 | 0 | 13.6 |
| 2 | 14:31:32 | 0 | 25.5 | 0 | 13.2 |
| 3 | 14:32:10 | 0 | 24.7 | 0 | 13.4 |
| 4 | 14:32:49 | 0 | 25.1 | 0 | 13.4 |
| 5 | 14:33:27 | 0 | 26.3 | 0 | 14.0 |
| 6 | 14:34:07 | 0 | 26.0 | 0 | 13.8 |
| 7 | 14:34:47 | 0 | 25.4 | 0 | 13.8 |
| 8 | 14:35:26 | 0 | 26.0 | 0 | 13.8 |
| 9 | 14:36:06 | 0 | 25.8 | 0 | 13.9 |
| 10 | 14:36:46 | 0 | 26.5 | 0 | 14.1 |
| 11 | 14:37:26 | 0 | 26.1 | 0 | 14.2 |
| 12 | 14:38:07 | 0 | 26.1 | 0 | 13.8 |

These cycles are diagnostic evidence about frequency only; they do not explain the one stall seen in Batch 7 and do not resolve REL-01.
