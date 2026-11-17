# Batch 7 diagnostic start/stop cycles

Run on 2026-11-13 after attempt 1 of the repeatability checkpoint failed with `api was not ready after 90s` (report `20261113-024551-f2bb`). These six cycles are DIAGNOSTIC, not part of the checkpoint: each ran `scripts/demo.py up` then `scripts/demo.py down` (readiness diagnostics enabled) to look for a recurrence. None was filtered out.

| Cycle | Start time | `up` exit | `down` exit |
|---|---|---|---|
| 1 | 02:52:01 | 0 | 0 |
| 2 | 02:52:40 | 0 | 0 |
| 3 | 02:53:19 | 0 | 0 |
| 4 | 02:53:59 | 0 | 0 |
| 5 | 02:54:38 | 0 | 0 |
| 6 | 02:55:18 | 0 | 0 |

Result: 6 of 6 cycles started every service and the API became ready; the stall did **not** recur, so its cause remains unestablished (see the Batch 7 report).
