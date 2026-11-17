# safety-v5 confirmation set: FROZEN

Frozen 2026-11-12 (EST). Code commit under test: `f8109881ff7f8a24d978c2a77c3b1740b9e48bbe` (shipped default configuration; no EAOP_TUNING, no candidate flags).
Dataset digests: `MANIFEST.sha256`. Implementation, scorer (`test_safety_acceptance_v5.py` and the scripted model in `test_safety_acceptance.py`) and generator digests: `CODE_AND_SCORER_SHA256.txt`.
Protocol: run once with `SAFETY_DATASET=safety-v5 SAFETY_ACCEPT_LABEL=final-v5`; the dataset, labels, scorer and code are not changed afterwards; a failing result is preserved and
reported, not patched against. No v5 case was used for development: development used the consumed sets safety-v1..v4 and separate regression tests; the v5 generator was
written before the first v5 run and never executed against the implementation.
Independence: fresh frozen confirmation set built by the same implementer; not external validation. Labels follow the V5 requirement text.

## Amendment (before any result existed)
The first execution aborted with an exception in the cross-tenant donor step of the harness (`AttributeError` while the scripted model parsed a Meridian report in the Apex tenant) and wrote no result file and no metric.
Only that step was changed (a failed donor filing is now tolerated); the dataset, labels, metrics and the implementation are unchanged. `CODE_AND_SCORER_SHA256.txt` records the amended harness digest.
