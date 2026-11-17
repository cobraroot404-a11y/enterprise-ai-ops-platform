# Measured performance and reliability figures

Every number here is copied from a committed artifact and checked against it by `tests/test_performance_docs.py`. Nothing is estimated. All measurements are from one CPU-only laptop (Intel i7-1165G7, 15.7 GB RAM), one user unless stated, local mock external systems, same-author suites. They are engineering measurements, not capacity claims and not production figures.

## Language-model paths (real Ollama `qwen2.5:1.5b` and MiniLM; Phase 8 baseline, development split)
Source: [phase8-baseline-report.md](../evaluation/phase8-baseline-report.md), section 5.

| Measurement | Result | Note |
|---|---|---|
| `/ai/ask` latency | p50 4.41 s, p95 12.43 s (n=118) | provisional budget 15 s p95: met on this sample |
| `/incidents/extract` latency | p50 3.40 s, p95 7.84 s (n=34) | |
| LLM inference rate | median 25.4 tokens per second | |
| Concurrency | at 4 simultaneous requests half were refused with 429 by the application's concurrency limiter | throughput scaling beyond 4 was not measured |
| Cold start | not measured | the model was already resident |

## Platform steps without a language model (deterministic backends; system time only)
Source: [evaluation/demo-runs/20261113-152713-c19b/comparison/comparison.json](../../evaluation/demo-runs/20261113-152713-c19b/comparison/comparison.json), 20 synthetic tasks, protocol in [evaluation/comparison/protocol.md](../../evaluation/comparison/protocol.md). These are **class A: measured automated system time**; they exclude human reading and thinking time, so they are not a workflow duration and not a productivity claim.

| Step | median s | p95 s |
|---|---|---|
| extract incident | 0.044 | 0.0655 |
| draft ticket | 0.0249 | 0.0287 |
| request approval | 0.0224 | 0.0256 |
| approve | 0.032 | 0.0336 |
| worker submission (outbox to mock ticketing) | 0.9166 | 1.034 |
| end to end, system time | 1.0679 | 1.1799 |

## Reliability and integration rates
| Measurement | Result | Evidence |
|---|---|---|
| Transient-failure recovery (defined 11-case suite) | 11 of 11 recovered, 0 duplicate external tickets | [recovery-rate-report.json](../../evaluation/recovery/recovery-rate-report.json) |
| Integration success (defined 14-run suite: REST, CSV, signed webhooks) | 14 of 14 | [integration-success-rate-report.json](../../evaluation/integration/integration-success-rate-report.json) |
| Fault injection and reliability scenarios | 15 of 15 passed | [fi-report.json](../../evaluation/failure-reports/phase7/fi-report.json) |
| Cold-start reliability (REL-01) | 12 of 12 further cycles clean; the defect remains **open** | [reliability-defect-register.md](../planning/reliability-defect-register.md) |

Both rate suites are coarse (one miss would be 9% and 7%) and exercise mock systems; their definitions are in the module docstrings of `tests/fault_injection/test_recovery_rate.py` and `backend/tests/test_integration_success_rate.py`.

## Not measured
Throughput under sustained load, memory growth over time, cold-versus-warm model behaviour, real network latency, any multi-machine figure, p99 (sample sizes are below 200).
