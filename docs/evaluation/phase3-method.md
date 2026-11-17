# Phase 3 evaluation method (real local AI)

Everything here is measured by `evaluation/benchmarks/run_phase3.py`. A run writes `results.json`, `manifest.json` and per-query JSONL files under `evaluation/reports/phase3/<run_id>/`. The manifest records the exact command, UTC timestamps, hardware, software versions, Ollama model digest, embedding model revision, prompt hash and dataset hash.

## Two evidence classes (never mixed)
- `real_ai`: LLM backend `ollama` (qwen2.5:1.5b, Q4_K_M, CPU) **and** embeddings `sentence_transformers` (all-MiniLM-L6-v2, pinned revision). Only these runs are AI results.
- `functional_only_deterministic_not_ai_performance`: the test-only extractive LLM and hashed bag-of-words embedder. They verify behaviour and provide a lexical baseline; their numbers are never reported as AI performance.

## Dataset: `apex-eval-v1` (synthetic, fictional)
Built by `evaluation/datasets/apex-eval-v1/build_dataset.py`: 6 equipment manuals, 2 inspection reports, an incident history CSV and an equipment register, loaded together with the 5 demo Apex files as distractors (about 100 chunks total, see `results.json`). Queries: 12 answerable + 4 unanswerable in a **dev** split (used only to calibrate the evidence threshold and iterate prompts) and 36 answerable + 8 unanswerable in a held-out **test** split (all reported numbers). 24 labelled fault reports score structured extraction. Relevance unit: `(filename, page)` for PDFs, `(filename, record_id)` for CSV rows.

## Metrics and denominators
- **Recall@5** (hybrid retrieval): per answerable test query, relevant units found in the top 5 / relevant units; mean over 36 queries.
- **Precision@5**: top-5 chunks belonging to a relevant unit / 5. Every query has exactly one relevant unit, so the maximum is 0.2; read it together with Recall@5, MRR and hit@1. Because the corpus is small (about 100 chunks), Recall@5 saturates easily; MRR, hit@1 and the vector-only / full-text-only ablations are more informative.
- **Evidence gate**: whether any retrieved non-suspicious passage passes the similarity threshold (0.50 for MiniLM, chosen on the dev split only). Reported on 36 answerable (should pass) and 8 unanswerable (should be blocked) test queries.
- **Groundedness rate**: answerable test queries whose answer was produced and fully verified / 36.
- **Citation correctness**: citations emitted by verified answers that point at a ground-truth relevant unit / citations emitted. **Citation validity** is guaranteed by construction (every emitted citation passed verbatim-quote verification); answers whose quotes fail verification are withheld and counted in `withheld_unverified_or_invalid`.
- **Key-fact coverage** (proxy for answer correctness): answers containing all expected key strings. It is a string-match proxy, not a human judgement.
- **Abstention**: correct abstentions on 8 unanswerable queries; false abstentions on the 36 answerable ones.
- **Structured output validity**: of 24 fault reports, how many raw model outputs parsed into the schema (and referenced an asset ID that appears in the report). Field accuracy is counted over valid outputs. Priority is decided by deterministic rules from the model's fields; the table reports priority agreement with labels derived from the expected fields.
- **Latency**: median and p95 with n; retrieval = query embedding + hybrid SQL; LLM inference = wall time of each Ollama call; end to end = extract incident, draft, request approval, approve, worker submit (5 repetitions). Tokens/s comes from Ollama's own counters.
- **Resources**: system CPU %, Ollama and Python working set sampled every ~3 s by a PowerShell sampler (the sampler itself adds a small load).

## Honest limits
- Small synthetic corpus and a single run (temperature 0, fixed seed); no confidence intervals. 36 test queries means one query is about 2.8 percentage points.
- The 1.5B model is weak at verbatim quoting; strict verification withholds those answers instead of showing unverified ones.
- Ground-truth labels were written by the project author, not independent annotators.
- No claims about real customer productivity are made.

## Reproduce
```bash
python scripts/fetch_models.py                       # pinned MiniLM (about 92 MB), the only implicit-download-free path
ollama pull qwen2.5:1.5b                             # 986 MB
python evaluation/benchmarks/run_phase3.py --embedding sentence_transformers --llm ollama
python evaluation/benchmarks/run_phase3.py --embedding deterministic --llm deterministic   # functional baseline
RUN_REAL_AI=1 python -m pytest backend/tests/test_real_ai.py -q                              # real-AI integration tests
python scripts/reindex_embeddings.py --tenant <slug> --backend sentence_transformers         # migrate a tenant's index
```
