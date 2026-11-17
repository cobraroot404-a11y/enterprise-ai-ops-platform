# EAOP 08F live owner observations

Checkout `9cd5d7fff296bfb468bacf9a186a40293f2b2fcc`. Demo run `20261116-152113-9846`, disposable database `eaop_demo_20261116_152113_9846`, URL `http://127.0.0.1:5173/`.

The owner reached all 27 steps in one continuous disposable session. Twenty-five passed for their documented scope and two were Partial (Apex integration configuration and the deterministic maintenance answer). The observations below distinguish live owner actions, retained evidence reviewed by the owner, and supporting system logs. Time zone throughout is Eastern Standard Time on November 16, 2026.

## Step 1 — Start the platform

PASS. The owner confirmed readiness before the START instruction, reported “40 seconds” after the STOP instruction, and confirmed the EAOP sign-in page appeared. Exact owner clock timestamps were not supplied. System start was 15:21:07.2588466 EST and READY was 15:21:35.3558071 EST on November 16, 2026 (28.0969605 seconds including disposable PostgreSQL). API health returned HTTP 200.

## Step 2 — Authenticate

PASS. The owner confirmed Apex Overview after signing in as the Apex engineer. The owner supplied screenshots of two input retries. The first showed an incorrect tenant and a mail-link prefix in the email field. The second showed the tenant field empty with the tenant-required validation message. Both inputs were corrected before the successful sign-in confirmation. No owner timing was supplied for this step.

## Step 3 — Onboard Apex

PASS. The launcher seeded Apex during startup. The owner observed “5 of 5 checks complete” on Apex Overview.

## Step 4 — Configure integrations

PARTIAL. The Apex engineer saw five document kinds, the tenant-administrator restriction on connector configuration, and no synchronisation or webhook deliveries. The owner confirmed the header showed Support engineer when verifying the account. Administrator connector configuration was not observed. Continue with the engineer workflow and revisit this step if an administrator becomes available during the session.

## Step 5 — Ingest equipment documents

PASS. The owner supplied a screenshot of the upload confirmation for the fictional `apex-owner-inspection-note.txt` and its v1 row in Document Library under `inspection_report`, with one passage. The owner reported 1.5 seconds. The API recorded POST /documents HTTP 201 at 15:35:16 EST and 91.6 ms of system processing. An earlier retry corrected a file-picker path transcription error before an upload was submitted.

## Step 6 — Ask maintenance question

PARTIAL. The owner showed a deterministic answer with citations at 15:39:13 EST and reported 0.8 seconds alongside that result. The HTTP 200 request at that displayed timestamp took 44.7 ms. The answer quoted the manual title and two register entries but did not provide the requested vibration recommendation. Two other replies reported 0.65 (unit unstated) and 0.4 seconds without identifying a specific visible answer. Those are retained as additional unpaired reports rather than substituted for the 0.8-second observation.

## Step 7 — Inspect citations

PASS. The owner expanded Inspect and reported `apex_cp200_pump_manual.pdf` v1, page 1, passage `4507092d-f843-454e-acf7-72f10cb9cb58`, and the character-for-character quote check. The quote was the fictional manual title. It did not support any particular vibration recommendation, as recorded in Step 6.

## Step 8 — Identify related incidents

PASS. The owner analysed the P-101 vibration report and observed P3, verified equipment, and related incidents INC-2025-0107, INC-2024-0412 and INC-2025-0633. Owner elapsed time was 0.8 seconds. API extraction returned HTTP 201 at 15:43:33 EST in 169.6 ms.

## Step 9 — Generate structured ticket

PASS. The owner confirmed the draft dialog and observed `[P3] mechanical vibration on P-101` in Draft state, dated 15:45:20 EST. The owner reported 1.8 seconds for the draft action. This and the separate 0.8-second incident report do not establish one continuous incident-to-ticket timing.

## Step 10 — Request approval

PASS. After confirming the request, the owner observed the ticket history transition from DRAFT to PENDING_APPROVAL at 15:47:28 EST, with no approval decision yet.

## Step 11 — Approve the ticket

PASS. The owner first saw the awaiting-decision ticket and explicit author/role refusal in the engineer session. The owner then confirmed the Maintenance supervisor header and approved P-101, observing “Approved. The ticket is queued for submission.” Owner elapsed was 0.7 seconds. The approval request returned HTTP 200 at 15:55:10 EST in 104.8 ms.

## Step 12 — Submit to mock API

PASS. The owner observed Submitted, external ID MNT-1001, one attempt, and update time 15:55:12 EST in Support Tickets. Worker logs measured 304.8 ms for the submission attempt. The logged approval-to-submission interval is approximately two seconds at one-second resolution. No separate owner submission timing was reported.

## Step 13 — Simulate API outage

PASS. The owner created and requested approval for a second P-101 ticket, then approved it as the supervisor and observed the queued notice after 0.6 seconds. The disposable mock was configured to return two HTTP 503 responses and its logs confirmed both. The owner then read both 503s and RETRY_PENDING transitions in ticket history at 16:02:35 and 16:02:37 EST.

## Step 14 — Demonstrate recovery

PASS. The owner observed the second ticket Submitted with external ID MNT-1002 at 16:02:41 EST, including the transition from retry to submission. The observed application event interval from approval to submission was about six seconds at one-second resolution. The separately reported 0.6 seconds measured the approval notice only. No owner stopwatch time for recovery was reported.

## Step 15 — Verify no duplicate ticket

PASS. The owner observed one row for MNT-1002 with three attempts and one separate row for MNT-1001 with one attempt. The disposable mock independently listed exactly those two external IDs, four total requests and zero pending faults. See `outage-result.json`.

## Step 16 — Display audit history

PASS. The owner reopened MNT-1002 and reported the history identifying the Apex engineer as draft author, the Apex supervisor as approver, and the worker as retry and submission actor. This observation covers ticket-level history.

## Step 17 — Onboard Meridian

PASS. The owner signed in as Meridian's support engineer and observed 5 of 5 onboarding checks, including the saved profile, authoritative fleet register, guidance documents, deterministic embedding profile, and a separate approver. Connector checks were unavailable to the engineer. The full Meridian stopwatch was requested before switching tenants. An exact owner start timestamp has not been supplied.

## Step 18 — Configure custom mappings

PASS for the applied profile review. The owner reported profile version 1, asset wording vehicle, authoritative register kind fleet_register, history kind service_history, the two guidance kinds and the fleet and CRM enrichments. The verified configuration was applied by startup; the owner did not edit it.

## Step 19 — Ingest fleet records

PASS for an owner-observed CSV import. After confirming the Meridian engineer header, the owner uploaded `meridian-owner-fleet.csv` as fleet_register and observed the v1, one-passage row at 16:21:44 EST alongside the five Meridian fixtures. A prior wrong-tab attempt uploaded the same fictional file to disposable Apex as equipment_manual at 16:18:00 EST. This was a tenant-selection mistake with two separate authenticated browser sessions. It is not used as Meridian evidence or as a tenant-isolation probe. Both rows are disposable.

## Step 20 — Generate and approve fleet ticket

PASS. The owner reported the verified P3 VH-2101 brake-system incident at 16:22:42 EST, drafted the ticket at 16:23:33, and requested approval at 16:23:53. The separate Meridian supervisor approved at 16:28:50 and the owner observed Submitted with mock work order WO-7001 at 16:28:51. The displayed approval-to-submission interval was approximately one second. No full Meridian owner stopwatch duration was supplied.

## Step 21 — Demonstrate tenant isolation

PASS. The owner opened the known Apex incident link while the UI identified the signed-in Meridian supervisor. Meridian's VH-2101 remained visible in the list, and the Apex detail displayed “Could not load incident: Incident not found.” The API corroborated the Apex detail and history refusals with HTTP 404 at 16:31 EST.

## Step 22 — Review customer acceptance tests

PASS (review). The owner explicitly confirmed reviewing the retained 21 passing deterministic acceptance tests, including both end-to-end tenant workflows. No rerun took place in this manual session.

## Step 23 — Review fault-injection tests

PASS (review). The owner displayed and reported the dashboard's retained 11 of 11 fault scenario results, explicitly including HTTP 503 and malformed response. The earlier focused FI-01 and FI-04 results were presented for review. This manual session also exercised the live ticketing mock's two 503s and observed recovery in Steps 13–15. No Gate C or fault suite rerun took place here.

## Step 24 — Review evaluation benchmarks

PASS (review). The owner displayed the historical evaluation dashboard and explicitly confirmed reviewing that result and the separate Phase 8 held-out results. The three presented target misses were citation correctness (89.8% vs 95%), grounded-answer coverage (59.3% vs 75%) and raw schema validity (90% vs 100%). No benchmark was rerun.

## Step 25 — Display verified results

PASS (review). The owner reviewed the project's verified engineering status after an explanation of the 203 verified, 28 partial, 3 missing and 4 not evaluable requirement dispositions and the scope of the 21 retained local acceptance passes.

## Step 26 — Explain cloud portability

PASS (review). The owner confirmed reviewing the documented illustrative blueprint, including separate API and worker compute, PostgreSQL with pgvector and tenant isolation, existing connector contracts, private networking and managed secrets. No deployment was performed.

## Step 27 — Explain architecture tradeoffs

PASS (review). The owner confirmed reviewing why the modular monolith and worker keep approval, audit and outbox writes in one transaction, and the separate scaling, distributed coordination, and isolation-validation costs of a microservices alternative.

## Keyboard and visible focus

The owner reported that Tab reached Refresh and Shift+Tab moved focus back to the Evaluation Dashboard link. The owner reported a visible ring on Evaluation Dashboard and supplied a screenshot showing a clear blue ring around Refresh. Keyboard navigation, reverse movement and visible focus passed for this observed pair. The first focus target after reload, skip link, full sidebar and route traversal, other links and form fields, incident selection, keyboard-only approval and rejection, dialog escape and focus return, and keyboard trap sweep were not confirmed. A dialog used during the ticket workflow does not establish how the owner navigated it. Narrator was outside this manual session.

## Owner timings

| Activity | Owner stopwatch | System or application evidence |
| --- | --- | --- |
| Platform startup | 40 s | 28.097 s from command boundary to READY, including PostgreSQL |
| Apex document ingestion | 1.5 s | HTTP 201 in 91.6 ms |
| Apex maintenance query | 0.8 s for the identified answer | HTTP 200 in 44.7 ms |
| Apex incident and ticket generation | 0.8 s extraction and 1.8 s draft, measured separately | Incident extraction HTTP 201 in 169.6 ms |
| Apex approval | 0.7 s for first approval; 0.6 s for the outage ticket's approval | First approval HTTP 200 in 104.8 ms |
| Apex mock submission | NOT OBSERVED | About 2 s between displayed approval and submission; 304.8 ms worker attempt |
| Outage recovery | NOT OBSERVED | About 6 s between displayed approval/first 503 and confirmed submission |
| Full Apex workflow | NOT OBSERVED | Workflow completed; no continuous owner stopwatch interval |
| Full Meridian workflow | NOT OBSERVED | Workflow completed; no continuous owner stopwatch interval returned |

Owner durations are reported elapsed times; exact owner START and STOP clock timestamps were not supplied. System timestamps above are not substitutes for owner measurements. These observations do not quantify customer productivity.

## Same-machine reproduction

The session is an **owner-observed same-machine compatible-hardware reproduction** of both synthetic tenant workflow paths, ending in MNT-1001 and WO-7001. The Windows 11 26H2 host reported build 26300.9974 and 16,805,040,128 bytes of RAM. The same hardware previously identified an Intel i7-1165G7 with eight logical processors and Iris Xe. This run used Docker Desktop 4.90.0 from the existing installation, live-queried Engine 29.7.2, Python 3.10.0, Node 24.13.1 and disposable PostgreSQL 16.15. Ollama client 0.40.16 was installed; the server was unreachable when checked. The demo used deterministic LLM and embedding backends, with no Ollama or GPU inference.

After recording the baseline, the operator used `docker compose --env-file .demo/08f-ui.env -p eaop08f-owner-9cd5d7f up -d --wait --pull never postgres` and the existing Python environment to run `scripts/demo.py up --env-file .demo/08f-ui.env`. Supporting logs are in `.demo/08f-owner-9cd5d7f/` and `.demo/20261116-152113-9846/logs/`. The one launcher API attempt reached HTTP 200, with no REL-01 stall observed. REL-01 remains open.

## Dispositions

- P32L1277 stays Partial. The owner reached all 27 steps in one session, with the two documented partial outcomes.
- P23L856 stays Partial. Owner reproduction on compatible hardware is now observed; reviewer reproduction from the handover remains unverified.
- P18L659 stays Partial. The focused visual and keyboard result is confirmed; full-route and dialog coverage remains open.
- Manual timing evidence advanced. Four of nine requested categories lack an owner duration, and incident and draft were measured separately.
- Register counts remain 203 Verified, 28 Partial, 3 Missing and 4 Not evaluable. The closure plan remains at 35 entries. Gate C remains closed. EAOP 08F and Phase 10 local evidence remain open. SAFE TO CLEAR: No.

## Cleanup and verification

The operator used `scripts/demo.py down --env-file .demo/08f-ui.env` to stop the eight recorded processes and drop this run's demo database. Compose down with volumes removed only `eaop08f-owner-9cd5d7f` and its container, network and volume. At 17:42:53 EST the post-run inventory matched two protected containers, ten volumes, fifteen images and all four networks. Full network inspections matched with no changed fields. No checked EAOP port remained listening. Baseline and post-run inventories, the mock count and launcher logs remain in the local session directory.

Twenty-nine focused evidence and governance tests passed, including closure-plan consistency. Reconciliation validated all 238 requirements, both traceability checks passed, and scoped Ruff passed. The previous acceptance and fault results were reviewed rather than rerun.
