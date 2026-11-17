# safety-v7 confirmation set: FROZEN

Frozen 2026-11-12 (EST). Code commit under test: `58e5fcb157019e575d19ec2fc50079f0eb5934a6` (shipped default configuration; no EAOP_TUNING, no candidate flags).
Dataset digests: `MANIFEST.sha256`; implementation, scorer (`test_safety_acceptance_v7.py`, scripted model in `test_safety_acceptance.py`) and generator digests: `CODE_AND_SCORER_SHA256.txt`.
Protocol: one run with `SAFETY_DATASET=safety-v7 SAFETY_ACCEPT_LABEL=final-v7`; dataset, labels, scorer and code unchanged afterwards; failures are preserved and reported, not patched against, and no further iteration or dataset is created automatically.
Development used the consumed sets safety-v1..v6 and separate regression tests; the v7 generator was written before this run and never executed against the implementation until freezing.
Independence: fresh frozen confirmation set built by the same implementer; not external validation. Labels derive from the V7 requirement text (see generator docstring).
