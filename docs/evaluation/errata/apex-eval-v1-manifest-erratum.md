# Erratum E-001: `apex-eval-v1` manifest (versioned 2026-11-11, written during Phase 8 preparation)

The original artifacts (`evaluation/datasets/apex-eval-v1/dataset_manifest.json`, `queries.jsonl`, and every Phase 3/4 report) are **unchanged**. This erratum only documents what they say.

## 1. The reported discrepancy ("manifest declares 4 queries, file holds 60") is not a defect
In the Gate B package I reported that the manifest field `queries` reads 4 while `queries.jsonl` has 60 lines. That was a misreading on my side: `queries` is an **object with four counters**
(`answerable_dev` 12, `answerable_test` 36, `unanswerable_dev` 4, `unanswerable_test` 8), and 12 + 36 + 4 + 8 = **60**, exactly the number of lines in `queries.jsonl`. A recount of the file by split and answerability
gives the same four numbers. The statement in `phase8-dataset-methodology.md` v1.0 and `phase8-evaluation-protocol.md` v1.0 is therefore withdrawn; v1.1 documents carry the correction.
Historical metrics are unaffected; no re-interpretation of any Phase 3/4 number is needed.

## 2. A different, real inconsistency found while checking: two hash algorithms under one name
| Where recorded | Key | Value | Algorithm | Reproduced? |
|---|---|---|---|---|
| `apex-eval-v1/dataset_manifest.json` | `text_files_sha256` | `0d89d1b8...9d9569` | `build_dataset.py`: SHA-256 over (file name + bytes) of the four text files `eval_equipment_register.csv`, `eval_incident_history.csv`, `queries.jsonl`, `reports.jsonl` (sorted; PDFs, the manifest and the build script excluded) | yes, recomputed identically |
| Phase 3 and Phase 4 run manifests (`evaluation/reports/phase3/*/manifest.json`, `phase4-remeasure`) | `dataset.text_files_sha256` | `e7401e1b...257167d` | `run_phase3.py`: SHA-256 over the concatenated bytes (no names) of all `.jsonl` and `.csv` files under the dataset directory | yes, recomputed identically |

Both values are correct for their own algorithm and the dataset files are byte-identical to the ones used in the runs; the same key name hides two different definitions, so the values must not be compared with each other.
**Effect:** none on any measured result; the run manifests identify the dataset they used. **Interpretation rule:** compare a run manifest hash only with a hash computed by the `run_phase3.py` method.
The eval-v2 dataset uses a per-file SHA-256 list (`MANIFEST.sha256`) and per-split hashes (`frozen_splits.json`) to avoid this ambiguity.

## 3. Root cause
Two independently written pieces of code (dataset builder in Phase 3, runner in Phase 3) each computed a "text files hash" with a different definition; neither documented the algorithm. No review step compared them.

## 4. Affected reports
Phase 3 (`evaluation/reports/phase3/*`) and Phase 4 re-measurement run manifests: field naming only. Retrieval, grounding and extraction metrics remain valid as reported (including citation correctness 89.3-92.6%, NOT MET).
