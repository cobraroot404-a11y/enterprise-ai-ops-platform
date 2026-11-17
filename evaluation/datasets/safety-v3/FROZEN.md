# safety-v3 acceptance set: FROZEN (final acceptance set)

Frozen 2026-11-12 (EST) after the second fix and before any run of this set. Files and digests: `MANIFEST.sha256`. Generator: `evaluation/safety/gen_safety_acceptance_v3.py` (seed 20261114).

safety-v1 and safety-v2 were used during development and fixing (`evaluation/reports/safety/dev-*`, `post-fix-v2.json`) and are development evidence only.
This set uses new wording and includes cases the author expects to stress the validator (unit synonyms, decimal commas, mixed signals). It is run exactly once
(label `post-fix-v3`); any failure is reported as a limitation and is not patched against this set.
Independence caveat: author-built synthetic cases; the author knows the implementation; adversarial model proposals are scripted, not produced by a real model.
