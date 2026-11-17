# Development experiment: the model invents asset ids (dev-noasset-v1)

**Status: development evidence only, same author. It justified one change; it confirms nothing.** The held-out and challenge splits are consumed and were not used.

## Why
On the consumed held-out split, raw extraction schema validity was 18 of 20 (90%): in both failures the report named no equipment and the model invented an asset id (the application rejected them, so no unsafe incident was created). The development split of `eval-v2` contains **no** such cases, so tuning for this failure needed new material. `evaluation/datasets/dev-noasset-v1/` holds 30 reports written fresh for this purpose (16 naming no equipment, 14 naming one or two ids), frozen by a SHA-256 manifest. Method and classification rules: `evaluation/phase8/run_noasset_dev.py`.

## Result (qwen2.5:1.5b via Ollama, temperature 0, fixed seed; one call per case and variant; runs `evaluation/reports/dev-noasset-v1/20261113T233214` (model-level only) and `.../20261113T233545` (adds the application-level asset, identical model results))
| Variant | No-asset reports: id invented | No-asset reports: null returned | Reports with ids: correct | Raw valid (not schema-invalid, not invented) |
|---|---|---|---|---|
| A: current prompt | **16 of 16** | 0 | 13 of 14 | 13 of 30 |
| B: prompt adds "asset_id MUST be null unless an id is written; never invent" | 15 of 16 | 1 | 13 of 14 | 14 of 30 |

The weakness is far larger than the held-out sample suggested (2 of 20): with this model and this schema, it fills the field with an invented id whenever none is written, and an explicit instruction barely changes that (1 of 16). **Prompt B was rejected** (a one-case difference is noise, as the optimisation log measured: about three queries of run-to-run variation).

## Change adopted
The asset id is no longer taken from the model. `choose_asset` (`backend/app/ai/ollama_llm.py`) takes the ids literally written in the report: none written gives no asset (the existing 422 `asset_not_identified` path); one gives that id; several give the model's pick if it is one of them, else the first written. The model's own value is recorded per call (`asset_model_output`: `null`, `agrees`, `chose_among_candidates`, `disagrees`, `invented`) so the weakness stays measurable and is **not hidden**. On the 30 development cases the application's asset was correct in **30 of 30** (model alone: 13 of 14 with ids, 0 of 16 without).

## What this does and does not show
- It removes a failure class by taking a task the model does badly out of its hands; it is not evidence that the model got better. The model-level raw validity (the metric that was 90%) will no longer count an invented id as an invalid output, because the application no longer depends on it. That makes the metric easier to meet, so any future claim must also quote `asset_model_output` and say so.
- Category and symptom extraction, the numeric trust boundary and priority rules are unchanged (priority is decided by deterministic rules; numbers from the model never drive it).
- Confirmation needs fresh, independently labelled reports that the author has not seen (Track 3 of the independent review package). Until then V41-21.x (raw validity) and V41-13.x stay Partial and the held-out figures in the README stay as measured.
- Limits: 30 cases, one model, one seed, author-written text; the candidate pattern needs letters-hyphen-digits ids (other formats such as `VH-2101` are handled by tenant profiles, whose path is unchanged).

Tests: `backend/tests/test_asset_identification.py` (rules, every development case, no exception on an invented id); `RUN_REAL_AI=1 python -m pytest backend/tests/test_real_ai.py` passed (12 tests) after the change.
