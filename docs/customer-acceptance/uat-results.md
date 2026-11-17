# Customer acceptance (UAT) results (Phase 7)

UAT-A01 to UAT-A08 (Apex Industrial Manufacturing, fictional) and UAT-B01 to UAT-B07 (Meridian Fleet Logistics, fictional), executed through
the real HTTP API against an isolated database and local mock external systems. Each scenario record in the JSON and Markdown reports holds
context, prerequisites, test data, steps, expected, actual, evidence, status and limitations.

```bash
UAT_BACKEND=deterministic python -m pytest tests/acceptance -q   # functional mode (test-only AI backends; not AI evidence)
UAT_BACKEND=real python -m pytest tests/acceptance -q            # real Ollama qwen2.5:1.5b + MiniLM (starts and needs Ollama)
```

Reports: `evaluation/customer-acceptance/{deterministic,real}/uat-report.{json,md}`. Deterministic-mode results are never presented as real-AI
evidence; AI-dependent acceptance rests on the real-mode run, whose assertions are thresholds on grounded behaviour (for example 2 of 3
questions grounded) because a 1.5B model is not deterministic. The end-to-end reliability tests (`tests/acceptance/test_end_to_end_reliability.py`)
run the full chain for both customers with injected 503, lost-response, 429 and malformed-response failures and reconcile the external system,
database and audit trail: no unauthorized action, no duplicate, correct isolation, accurate final states, human-review gate intact.

## Deterministic mode

15 of 15 passed (Deterministic TEST-ONLY backends: workflow, security and integration evidence only; NOT acceptance evidence for AI behaviour.).

| ID | Customer | Scenario | Requirements | Actual | Result |
|---|---|---|---|---|---|
| UAT-A01 | Apex Industrial Manufacturing | Document ingestion | R12.1, R12.2, R12.3 | 5 documents ingested {'apex_cp200_pump_manual.pdf': ('created', 3), 'apex_inspection_report_2026q3.pdf': ('created', 1), 'equipment_register.csv': ('created', 4), 'incident_history.csv': ('created', 5), 'maintenance_log. | PASS |
| UAT-A02 | Apex Industrial Manufacturing | Evidence-grounded retrieval | R13.1, R13.2, R13.3 | 3 of 3 answerable questions grounded with verified citations; out-of-scope question refused | PASS |
| UAT-A03 | Apex Industrial Manufacturing | Historical incident matching | R14.2, R7.1 | related incidents ['INC-2025-0107', 'INC-2024-0412', 'INC-2025-0633']; first is same-asset | PASS |
| UAT-A04 | Apex Industrial Manufacturing | Structured ticket generation | R14.1, R14.3, R14.4, R7.1 | incident pending_review (category mechanical_vibration, 2 citation(s)); draft DRAFT | PASS |
| UAT-A05 | Apex Industrial Manufacturing | Unapproved submission blocked | R15.1, R15.2, R16.2 | submit before approval 409; engineer approval 403; rejected ticket submit/retry 409; worker idle; mock requests 0 | PASS |
| UAT-A06 | Apex Industrial Manufacturing | Approved ticket submission | R15.1, R11.1, R15.5, R7.1 | ticket SUBMITTED as MNT-1006; 1 external ticket; audit has draft, approval, submission | PASS |
| UAT-A07 | Apex Industrial Manufacturing | Duplicate prevention | R15.3, R15.6, R11.3 | draft codes [201, 409, 409, 409, 409]; approval codes [200, 409, 409, 409, 409, 409]; worker ['retry_scheduled', 'submitted']; external tickets 1 | PASS |
| UAT-A08 | Apex Industrial Manufacturing | API failure recovery | R15.4, R11.2, R15.3 | 503 x2: ['retry_scheduled', 'retry_scheduled', 'submitted'], attempts 3; 400: FAILED then supervisor retry SUBMITTED; external tickets 2 for 2 tickets | PASS |
| UAT-B01 | Meridian Fleet Logistics | Second-tenant onboarding | R10.1, R10.3, R8.1 | 8 of 8 onboarding checks pass; profile v1; no customer-specific tables | PASS |
| UAT-B02 | Meridian Fleet Logistics | Customer-specific schema mapping | R10.2, R12.3 | service record SR-3002 and register record VH-2101 carry mapped columns | PASS |
| UAT-B03 | Meridian Fleet Logistics | Fleet issue extraction | R14.1, R14.3, R8.1 | VH-2101 verified; category brake_system; priority P2; 2 citation(s); enrichments present | PASS |
| UAT-B04 | Meridian Fleet Logistics | Ticket approval | R15.1, R15.2, R8.1 | author approval 403; supervisor approval recorded with comment; ticket APPROVED | PASS |
| UAT-B05 | Meridian Fleet Logistics | Correct customer API submission | R11.1, R10.2, R8.1 | work order WO-7004 with mapped fields; Apex system received only its own ticket | PASS |
| UAT-B06 | Meridian Fleet Logistics | Cross-tenant access denied | R16.1, R8.1 | 12 of 12 cross-tenant attempts denied; searches stayed inside each tenant; audit trails separate | PASS |
| UAT-B07 | Meridian Fleet Logistics | Failure recovery | R15.4, R15.3, R11.2 | 503: ['retry_scheduled', 'submitted']; lost response: ['retry_scheduled', 'submitted']; work orders 2 for 2 tickets | PASS |

## Real AI mode (Ollama + MiniLM)

15 of 15 passed (Real Ollama (qwen2.5:1.5b) + MiniLM: acceptance evidence for AI behaviour.).

| ID | Customer | Scenario | Requirements | Actual | Result |
|---|---|---|---|---|---|
| UAT-A01 | Apex Industrial Manufacturing | Document ingestion | R12.1, R12.2, R12.3 | 5 documents ingested {'apex_cp200_pump_manual.pdf': ('created', 3), 'apex_inspection_report_2026q3.pdf': ('created', 1), 'equipment_register.csv': ('created', 4), 'incident_history.csv': ('created', 5), 'maintenance_log. | PASS |
| UAT-A02 | Apex Industrial Manufacturing | Evidence-grounded retrieval | R13.1, R13.2, R13.3 | 3 of 3 answerable questions grounded with verified citations; out-of-scope question refused | PASS |
| UAT-A03 | Apex Industrial Manufacturing | Historical incident matching | R14.2, R7.1 | related incidents ['INC-2025-0107', 'INC-2024-0412', 'INC-2025-0633']; first is same-asset | PASS |
| UAT-A04 | Apex Industrial Manufacturing | Structured ticket generation | R14.1, R14.3, R14.4, R7.1 | incident pending_review (category mechanical_vibration, 1 citation(s)); draft DRAFT | PASS |
| UAT-A05 | Apex Industrial Manufacturing | Unapproved submission blocked | R15.1, R15.2, R16.2 | submit before approval 409; engineer approval 403; rejected ticket submit/retry 409; worker idle; mock requests 0 | PASS |
| UAT-A06 | Apex Industrial Manufacturing | Approved ticket submission | R15.1, R11.1, R15.5, R7.1 | ticket SUBMITTED as MNT-1006; 1 external ticket; audit has draft, approval, submission | PASS |
| UAT-A07 | Apex Industrial Manufacturing | Duplicate prevention | R15.3, R15.6, R11.3 | draft codes [201, 409, 409, 409, 409]; approval codes [200, 409, 409, 409, 409, 409]; worker ['retry_scheduled', 'submitted']; external tickets 1 | PASS |
| UAT-A08 | Apex Industrial Manufacturing | API failure recovery | R15.4, R11.2, R15.3 | 503 x2: ['retry_scheduled', 'retry_scheduled', 'submitted'], attempts 3; 400: FAILED then supervisor retry SUBMITTED; external tickets 2 for 2 tickets | PASS |
| UAT-B01 | Meridian Fleet Logistics | Second-tenant onboarding | R10.1, R10.3, R8.1 | 8 of 8 onboarding checks pass; profile v1; no customer-specific tables | PASS |
| UAT-B02 | Meridian Fleet Logistics | Customer-specific schema mapping | R10.2, R12.3 | service record SR-3002 and register record VH-2101 carry mapped columns | PASS |
| UAT-B03 | Meridian Fleet Logistics | Fleet issue extraction | R14.1, R14.3, R8.1 | VH-2101 verified; category leak; priority P2; 0 citation(s); enrichments present | PASS |
| UAT-B04 | Meridian Fleet Logistics | Ticket approval | R15.1, R15.2, R8.1 | author approval 403; supervisor approval recorded with comment; ticket APPROVED | PASS |
| UAT-B05 | Meridian Fleet Logistics | Correct customer API submission | R11.1, R10.2, R8.1 | work order WO-7004 with mapped fields; Apex system received only its own ticket | PASS |
| UAT-B06 | Meridian Fleet Logistics | Cross-tenant access denied | R16.1, R8.1 | 12 of 12 cross-tenant attempts denied; searches stayed inside each tenant; audit trails separate | PASS |
| UAT-B07 | Meridian Fleet Logistics | Failure recovery | R15.4, R15.3, R11.2 | 503: ['retry_scheduled', 'submitted']; lost response: ['retry_scheduled', 'submitted']; work orders 2 for 2 tickets | PASS |

## Limitations

Meridian has no AI-quality benchmark (Phase 8). Both customers are fictional. About three quarters of AI-extracted incidents are held for
human review with the approved model; the review gate is not weakened to improve acceptance.
