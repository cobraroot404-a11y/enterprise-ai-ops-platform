# safety-v1 acceptance set: FROZEN

Frozen 2026-11-12 (EST) before any fix to the numeric-measurement path existed and before any measurement of the shipped default on it.
Files and digests: `MANIFEST.sha256`. Generator: `evaluation/safety/gen_safety_acceptance.py` (seed 20261112).

Rules: the set is never edited, relabelled or used to tune the fix. Debugging uses separate regression cases in `backend/tests/test_numeric_safety.py`.
It is run exactly twice: once against the shipped default before the fix (evidence of the defect), once against the fixed code (acceptance).

Independence caveat: author-built synthetic cases; the author knows the implementation; adversarial model proposals are scripted, not produced by a real model.
It is a fresh set (not the consumed Phase 8 held-out split) but it is not an independent third-party validation.
