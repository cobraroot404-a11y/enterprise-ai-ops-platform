# Meridian real-AI smoke test (20261111T224043Z_meridian_smoke)

**Limited functional smoke testing. Not a statistically representative AI-quality benchmark.** The inputs are a handful of hand-written questions and reports over a 15-chunk synthetic corpus. No precision, recall, citation accuracy or other rate is claimed. Multi-tenant benchmarking is reserved for Phase 8.

Models: Ollama 0.40.16 `qwen2.5:1.5b` (digest `65ec06548149b04c...`), sentence_transformers:sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4706b3f48f1d95db1a4f5529b4d41:384. Raw outputs: `raw.json`; per-check results: `checks.json`; configuration: `manifest.json`.

Result: **17 of 17 functional checks passed.**

| Check | Property | Result |
|---|---|---|
| S0 | Meridian tenant is indexed with the real MiniLM profile (not the deterministic embedder) | PASS |
| S1 | Every retrieved chunk for every search belongs to Meridian (and each search returned results) | PASS |
| S2a | Every citation emitted points at a current Meridian-owned chunk | PASS |
| S2b | Every emitted citation quote is verbatim text of the cited chunk | PASS |
| S2c | The out-of-scope question received no answer and no citations | PASS |
| S3a | Asset ID extracted exactly as written in every report that contains one | PASS |
| S3b | Priority is exactly what the tenant's deterministic rules give for the extracted category and the regex-derived readings (the model never sets priority) | PASS |
| S3c | The report without a vehicle ID is rejected (asset_not_identified) rather than guessed | PASS |
| S4 | Registered vehicles are verified against the fleet register; the unregistered VH-9999 is not | PASS |
| S5a | review_status is pending_review only when the vehicle is registered AND grounded evidence exists | PASS |
| S5b | No ticket can be drafted from an incident in needs_review (HTTP 409) | PASS |
| S6a | A supervisor-accepted incident for an UNREGISTERED vehicle still cannot be approved for release | PASS |
| S6b | Approved ticket was submitted once to Meridian's service desk and stored with a WO- id | PASS |
| S6c | Customer-specific mapping applied: payload keys and urgency follow Meridian's connector config | PASS |
| S6d | Apex's maintenance ticketing system received nothing from Meridian's workflow | PASS |
| S7 | Audit trail contains every expected event type for the exercised workflow | PASS |
| S8 | Apex users cannot read or act on Meridian objects (and vice versa), and Apex retrieval never returns Meridian chunks | PASS |
