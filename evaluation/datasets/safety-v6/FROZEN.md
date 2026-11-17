# safety-v6 confirmation set: FROZEN

Frozen 2026-11-12 (EST). Code commit under test: `a1b33f8af2c4913bc7193a43d0470f3f65701fd9` (shipped default configuration; no EAOP_TUNING, no candidate flags).
Dataset digests: `MANIFEST.sha256`; implementation, scorer (`test_safety_acceptance_v5.py`, scripted model in `test_safety_acceptance.py`) and generator digests: `CODE_AND_SCORER_SHA256.txt`.
Protocol: one run with `SAFETY_DATASET=safety-v6 SAFETY_ACCEPT_LABEL=final-v6` (same scorer as safety-v5, unchanged); no change to dataset, labels, scorer or code afterwards; failures are preserved and reported, not patched against.
Development used the consumed sets safety-v1..v5 and separate regression tests; the v6 generator was written before this run and never executed against the implementation until freezing.
Independence: fresh frozen confirmation set built by the same implementer; not external validation. Labels derive from the V6 requirement text (see generator docstring).
