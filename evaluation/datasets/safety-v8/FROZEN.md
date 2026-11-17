# safety-v8 architectural confirmation set: FROZEN

Frozen 2026-11-12 (EST). Code commit under test: `36d5eba8a0bf10896384b4f8799e71d59edeaa54` (shipped default configuration; no EAOP_TUNING, no candidate flags; the harness sets only the simulation fixture key for the run).
Dataset digests: `MANIFEST.sha256`; implementation, scorer (`test_safety_acceptance_v8.py`, scripted model in `test_safety_acceptance.py`) and generator digests: `CODE_AND_SCORER_SHA256.txt`.
Protocol: one run with `SAFETY_DATASET=safety-v8 SAFETY_ACCEPT_LABEL=final-v8`; dataset, labels, scorer and code unchanged afterwards; failures are preserved and reported, not patched against; no further acceptance set or remediation iteration is created automatically.
Development used the consumed sets safety-v1..v7 as regression inputs (their labels predate the V8 trust policy), separate regression tests, and a throw-away smoke dataset with different wording used only to debug the harness (deleted, not committed); one harness-driven fix (audit event fields) was made before freezing.
Independence: fresh frozen confirmation set built by the same implementer; not external validation. Labels derive from the V8 requirement text (see generator docstring).
