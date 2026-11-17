# safety-v2 acceptance set: FROZEN

Frozen 2026-11-12 (EST), after the fix (commit `48a5f18`) and before any run of this set. Files and digests: `MANIFEST.sha256`.
Generator: `evaluation/safety/gen_safety_acceptance_v2.py` (seed 20261113).

Why v2: safety-v1 was run once against the patched validator before the regression suite existed (`evaluation/reports/safety/dev-debug-post-on-v1.json`);
it exposed two defects (asset identifier between measurement name and value hid a genuine reading; attribution used the nearest rather than the
preceding asset), which were fixed. v1 is therefore development evidence, not independent acceptance. v2 uses a new seed and different phrasings and
was run by no code before freezing.

Rules: never edited, never used to tune. Run exactly once on the fixed code (label `post-fix-v2`). Any failure is reported, not patched against this set.
Independence caveat: author-built synthetic cases; the author knows the implementation; adversarial model proposals are scripted.
