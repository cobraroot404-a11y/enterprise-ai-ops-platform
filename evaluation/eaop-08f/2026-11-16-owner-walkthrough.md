# EAOP 08F · Owner walkthrough evidence

Session checkout `f52304c8912f18f49cd67ff7cd8e142ac2eca71c`. Times below are Eastern on November 16, 2026. System observations and owner observations are recorded separately. Evidence filenames are under `.demo/08f-owner-f52304c/`, except `api.log` under `.demo/20261116-151130-822b/logs/` and the linked repository documentation.

| # | Action | Expected | Start–end | Actual | Evidence path | Disposition |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Start platform | Disposable PostgreSQL and UI become ready | 15:11:24.149–15:11:52.878 | Launcher READY and API health 200 | launcher.log, api.log | PASS (system) |
| 2 | Authenticate | Engineer reaches Overview after signing in | — | No current owner observation | — | NOT OBSERVED |
| 3 | Onboard Apex | Apex fixtures seed and tenant is usable | 15:11:37–15:11:38 | Seed step completed. Owner tenant verification pending | launcher.log | PARTIAL |
| 4 | Configure integrations | Show the Apex connector and its configured mock source | — | No current owner observation | — | NOT OBSERVED |
| 5 | Ingest equipment documents | Import an equipment document and show it in Document Library | — | No current owner observation | — | NOT OBSERVED |
| 6 | Ask a maintenance question | Ask about P-101 vibration and see a grounded response | — | No current owner observation | — | NOT OBSERVED |
| 7 | Inspect citations | Open the cited source and compare the supporting quote | — | No current owner observation | — | NOT OBSERVED |
| 8 | Identify related incidents | Open the P-101 incident and show related history | — | No current owner observation | — | NOT OBSERVED |
| 9 | Generate a structured ticket | Create a structured P-101 draft | — | No current owner observation | — | NOT OBSERVED |
| 10 | Request approval | Engineer moves the ticket to PENDING_APPROVAL | — | No current owner observation | — | NOT OBSERVED |
| 11 | Approve the ticket | Different supervisor approves and records a reason | — | No current owner observation | — | NOT OBSERVED |
| 12 | Submit to mock API | Worker submits and UI shows a mock external ID | — | No current owner observation | — | NOT OBSERVED |
| 13 | Simulate API outage | Mock returns HTTP 503 during ticket submission | 15:13:49–15:13:57 (suite) | FI-01 observed two 503s in the isolated test fixture | fi.log, fault_injection/fi-report.json | PASS (system, scoped) |
| 14 | Demonstrate recovery | Outbox retries and ticket reaches SUBMITTED | 15:13:49–15:13:57 (suite) | FI-01 and FI-04 both recovered to SUBMITTED | fault_injection/fi-report.json | PASS (system, scoped) |
| 15 | Verify no duplicate ticket | Retry leaves exactly one ticket at the mock | 15:13:49–15:13:57 (suite) | FI-01 and FI-04 each reported zero duplicate external actions | fault_injection/fi-report.json | PASS (system, scoped) |
| 16 | Display audit history | Show draft, approval, submission and state transitions | — | No current owner observation | — | NOT OBSERVED |
| 17 | Onboard Meridian | Public API creates Meridian and owner can access its Overview | 15:11:49–15:11:50 | Launcher completed public API onboarding. Owner review pending | launcher.log, api.log | PARTIAL |
| 18 | Configure custom mappings | Show Meridian profile and service-desk field mappings | — | No current owner observation | — | NOT OBSERVED |
| 19 | Ingest fleet records | Run a Meridian import and verify records are visible | — | No current owner observation | — | NOT OBSERVED |
| 20 | Generate and approve fleet ticket | Draft VH-2101, request approval and approve as a different supervisor | — | No current owner observation | — | NOT OBSERVED |
| 21 | Demonstrate tenant isolation | Show tenant boundary for records or objects | — | No current owner observation | — | NOT OBSERVED |
| 22 | Run customer acceptance tests | Execute deterministic acceptance suite on disposable PostgreSQL | 15:13:07–15:13:49 | 21 tests passed, including Apex and Meridian end-to-end reliability. Owner review pending | uat.log, acceptance/uat-report.json | PASS (system) |
| 23 | Run fault-injection tests | Execute scoped mock outage and malformed-response scenarios | 15:13:49–15:13:57 | FI-01 and FI-04 passed. The report generator prints a generic full-suite command; only those two nodes ran | fi.log, fault_injection/fi-report.json | PASS (system, scoped) |
| 24 | Run evaluation benchmarks | Review the retained benchmark and its unmet thresholds | — | Benchmark rerun deferred. Owner review pending | ../../docs/evaluation/phase8-heldout-report.md | NOT OBSERVED |
| 25 | Display verified results | Review the verified results section and its limits | — | Owner review pending | ../../README.md#verified-engineering-results | NOT OBSERVED |
| 26 | Explain cloud portability | Explain illustrative deployment and invariant contracts | — | Document describes separately deployed API and worker, managed PostgreSQL with pgvector, private networking and managed secrets. Blueprint review only | ../../docs/architecture/cloud-portability.md | PARTIAL (document review) |
| 27 | Explain architecture tradeoffs | Explain why the project uses a modular monolith and worker | — | Document contrasts one transaction for approval, outbox and audit with independently scalable services and their coordination cost. Document review only | ../../docs/architecture/deployment-tradeoffs.md | PARTIAL (document review) |

## Owner keyboard and timing checklist

1. Open the demo at `http://127.0.0.1:5173`. Use the existing local demo password. At sign-in and on every main route, use Tab and Shift+Tab. Record the first visible focus indicator, skip-link landing point, sidebar order and any unreachable control or keyboard trap. Include buttons, links and form fields.
2. As the Apex engineer, time document import through visible completion, the P-101 maintenance question through answered, and incident entry through structured ticket draft. Open the cited quote and select the incident from the list. Record the full Apex interval from sign-in through confirmed mock submission.
3. Request approval, switch to the Apex supervisor and time approval separately from worker submission. Open a confirmation dialog, record initial focus, press Escape and check where focus returns. Use a second disposable ticket to complete rejection and record its UI result. Review the audit history.
4. Repeat the ticket flow for VH-2101 in Meridian and record the full Meridian interval through visible mock submission. Record the Meridian mapping and fleet ingestion result and check the tenant boundary.
5. Review the current outage evidence and record the observed recovery result. Review the retained benchmark, verified results and the two architecture documents. Report actual start/end or elapsed time, outcome and what was visible. Use NOT OBSERVED for anything skipped.

Narrator speech was removed from this session at the owner's direction. No native Narrator observation is claimed.

## System observations

Disposable Compose project `eaop08f-owner-f52304c` started PostgreSQL 16.15 on loopback port 15432 with the existing pgvector image. The launcher ran `scripts/demo.py up --env-file .demo/08f-ui.env` with the existing Python environment, deterministic LLM and deterministic embeddings. Windows 11 26H2 build 26300.9974, Intel Core i7-1165G7 with eight logical processors, Intel Iris Xe, Docker Desktop 4.90.0, Docker Engine 29.7.2, Python 3.10.0 and Node 24.13.1 were observed. Ollama client 0.40.16 was present and its server was not reachable during the version check. No Ollama model or GPU inference was used. The two acceptance workflows used this same Windows machine and isolated test database. This does not establish an independent or fresh-machine reproduction.

The host reported 16,805,040,128 bytes of RAM (15.65 GiB) and WSL 2.7.13.0. System startup took 28.73 seconds including PostgreSQL. The single API start began at 15:11:47 and first returned health HTTP 200 at 15:11:49, approximately two seconds at log resolution. The application measured 45.6 ms for that request. REL-01 did not recur on this attempt and remains open. Neither suite wall time measures manual activity or production retry duration.

## Cleanup and protected resources

At 15:17:11, `scripts/demo.py down --env-file .demo/08f-ui.env` stopped the eight recorded processes and dropped the walkthrough database. Compose then removed only the PostgreSQL container, volume and network under `eaop08f-owner-f52304c`. Post-run inventory finished at 15:17:14 with no checked EAOP listener remaining.

The before and after captures in the session directory matched on both protected container identities, state, image, labels, mounts, ports and network names. They matched on all ten volume identities and listed configuration, and all fifteen image identities and tags. Full network inspections matched for all four networks, including IDs, configuration and attachment maps. This comparison applies to this run's new baseline.

## Owner results

No owner sign-in result or later browser observations were received. Keyboard order, reverse tabbing, visible focus, skip link, sidebar, links, buttons, fields, incident selection, approval, rejection, dialog focus, Escape, focus return and keyboard traps are all NOT OBSERVED in this session. The earlier scoped keyboard observations carry forward.

| Activity | System timing | Owner/manual timing |
| --- | --- | --- |
| Startup | 28.73 s including PostgreSQL | NOT OBSERVED |
| Document ingestion | No separate measurement | NOT OBSERVED |
| Maintenance retrieval | No separate measurement | NOT OBSERVED |
| Incident and ticket generation | No separate measurement | NOT OBSERVED |
| Approval | No live owner-flow measurement | NOT OBSERVED |
| Mock submission | No live owner-flow measurement | NOT OBSERVED |
| Outage recovery | Scoped suite wall time of 8.02 s includes both scenarios and harness setup | NOT OBSERVED |
| Full Apex workflow | No separate live workflow measurement | NOT OBSERVED |
| Full Meridian workflow | No separate live workflow measurement | NOT OBSERVED |

P32L1277, P23L856 and P18L659 remain Partial. The suite results add current deterministic system evidence for both tenants, but no reviewer walkthrough or owner visual focus was observed. Fresh AI confirmation, REL-01, and Phase 10 rollups remain open. The register stays at 203 Verified, 28 Partial, 3 Missing and 4 Not evaluable, with 35 closure-plan entries. Local technical completion and Phase 10 local evidence completion remain open. SAFE TO CLEAR: No.

Focused repository checks passed 29 tests, including closure-plan consistency. V4.1 reconciliation validated 238 requirements, both traceability checks passed, and scoped Ruff, secret scan, provenance and whitespace checks passed. Generated observability samples from the acceptance run were retained in the ignored session directory and the tracked historical samples were restored.
