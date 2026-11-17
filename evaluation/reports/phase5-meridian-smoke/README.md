# Meridian real-AI smoke evaluation

**Limited functional smoke testing, not an AI-quality benchmark.** Real Ollama (`qwen2.5:1.5b`) and MiniLM against Meridian's
actual tenant documents, in an isolated database (`eaop_smoke`), with an Apex tenant for cross-tenant denial checks.

Reproduce: `python scripts/ollama_ctl.py start && python evaluation/smoke/meridian_smoke.py`.
Each run directory holds `raw.json` (all inputs and raw outputs), `checks.json`, `manifest.json` (command, versions, model
digest, hardware, config hash) and `SUMMARY.md`. No precision, recall or citation-accuracy figure is computed or claimed.

## Runs
- `20261111T223853Z_meridian_smoke`: 16 of 17 checks passed. The failing check, S3b, was **mis-specified**: it expected the
  priority implied by the keywords in the report text, but priority follows the category the *model* extracts. This run is
  kept unmodified as the record of why the check was corrected.
- `20261111T224043Z_meridian_smoke`: S3b redefined as "priority equals the deterministic rule outcome for the extracted
  category and regex readings"; **17 of 17 checks passed**.

## Observation worth recording (`category_observations` in raw.json)
The model chose category `leak` for a low-brake-pressure report (R1) and for a flat-tyre report (R4), where the profile's
keyword rule gives `brake_system` and `tire_wheel`. For R4 this raised the priority to P2 where a keyword reading would
give P3, because priority is deterministic **given the extracted category**. Priority is never chosen by the model, but a
model misclassification can change it, which is one more reason the human-review gate and the later evaluation matter.
Five inputs say nothing about how often this happens: it is an anecdote, not a rate.
