# safety-v4 acceptance set: FROZEN (confirmation set for the final code)

Frozen 2026-11-12 (EST) after the third fix and before any run of this set. Files and digests: `MANIFEST.sha256`. Generator: `evaluation/safety/gen_safety_acceptance_v4.py` (seed 20261115).

safety-v1, v2 and v3 were consumed in development (each exposed defects that were then fixed; see `evaluation/reports/safety/`). v4 is new wording and includes
legitimate reports containing words the instruction detector watches, multi-line / table reports, and alarm-threshold numbers that are not readings.
Run exactly once (label `final-v4`). Failures are reported as limitations and not patched against this set.
Independence caveat: author-built synthetic cases; the author knows the implementation; adversarial model proposals are scripted.
