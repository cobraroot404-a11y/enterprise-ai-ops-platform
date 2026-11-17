# Phase 9–10 exit evidence

> **Current status.** [Gate C owner disposition](gate-c-owner-disposition.md) records technical acceptance complete and owner disposition closed for the pinned candidate, with the reproduction and accessibility evidence gaps retained. EAOP 09 is next. Phase 10 exit, publication, and release remain owner-gated. See the [EAOP 08E governance policy](eaop-08e-owner-governance.md). The checkpoint below preserves the historical assessment and its original dispositions.

Initially assessed 2026-11-15 against `db29198a41c9a7a1d34b1ca4629d49b942cf093b`. The [same-day local Terraform checkpoint](../../evaluation/terraform/provider-validation.md) adds provider validation evidence. **P31L1138 and P31L1229 remain Partial.** The [byte-pinned specification](../specification/ORIGINAL_MASTER_SPECIFICATION_V4.1.txt) controls the criteria. The register IDs are V41-31.01 and V41-31.02. The roadmap lists deliverables and the phase-end clause lists actions. Repository phase names and spec phase names differ. The [retrospective Phase 1–4 record](retrospective-phase-gates-1-4.md) gives the crosswalk. A row with several criteria applies its finding to each named criterion. In mixed rows, classify artifacts and missing evidence separately.

## P31L1138 · implementation roadmap

Original specification, lines 1138–1227.

```text
Phase 1: Foundation

* Environment verification
* GitHub identity verification
* Repository initialization
* License
* Project structure
* Docker
* Database
* CI

Phase 2: Customer onboarding and integration

* Authentication
* Tenant model
* RBAC
* Customer onboarding
* Connectors
* Mock APIs

Phase 3: Document intelligence

* Ingestion
* Metadata
* Embeddings
* Vector indexing
* Hybrid retrieval
* Local inference
* Citations

Phase 4: Workflow automation

* Incident extraction
* Ticket drafting
* Approval
* State machine
* External submission
* Recovery

Phase 5: Customer dashboard

* Frontend
* Document explorer
* AI assistant
* Incident explorer
* Approval queue
* Metrics

Phase 6: Security and reliability

* Tenant isolation
* Authorization tests
* Prompt-injection tests
* Audit logging
* Observability
* Fault injection

Phase 7: Customer acceptance

* Apex UAT
* Meridian UAT
* Requirements traceability
* Acceptance reports

Phase 8: Evaluation

* Retrieval benchmarks
* Citation evaluation
* Workflow benchmarks
* Failure recovery
* Business workflow comparison

Phase 9: Cloud portability

* Cloud-ready architecture
* Terraform/OpenTofu examples
* Local validation
* Deployment tradeoffs
* Optional Kubernetes examples

Phase 10: Documentation and release

* README
* Customer discovery documents
* Architecture documentation
* Deployment runbook
* Technical demonstration
* Security review
* GitHub audit
* Versioned release
```

| Requirement | Acceptance criterion | Existing evidence | Evidence quality | Satisfied? | Remaining gap |
|---|---|---|---|---|---|
| P31L1138 | Phase 1, Environment verification | `evaluation/environment/verification.md` records actual local hardware and tools. | deterministic current validation | Yes, as a roadmap deliverable | The later artifact cannot evidence a Phase 1 exit check. |
| P31L1138 | Phase 1, GitHub identity verification | `docs/planning/publication-handoff.md` gives the steps. | retrospective reconstruction for the work-to-date summary, missing for identity verification | No | Hard owner/external gate. Verify the authorized GitHub account. Local Git identity is a separate fact. |
| P31L1138 | Phase 1, Repository initialization, License, Project structure, Docker, Database | Foundation commit `d24f4ba` and its `CHANGELOG.md`, `LICENSE`, `docker-compose.yml` and `infrastructure/docker/postgres-init.sql`. | contemporaneous direct evidence | Yes for the listed foundation artifacts | The artifacts alone leave the phase-end actions open. |
| P31L1138 | Phase 1, CI | `d24f4ba:.github/workflows/ci.yml` and the current `.github/workflows/ci.yml` supply the workflow. `docs/operations/ci-and-local-tests.md` records its execution limit. | contemporaneous direct evidence for the workflow, missing for execution | Partial | First green remote CI is an external gate and a Part 32 release blocker. |
| P31L1138 | Phase 2, Authentication, Tenant model, RBAC, Connectors, Mock APIs | `docs/architecture/phase2-apex-slice.md` and `evaluation/reports/phase2-gate/manifest.json` record the tested slice, with deterministic backends and mocks. | contemporaneous direct evidence | Yes, within the demonstrated local scope | No scope extension inferred. |
| P31L1138 | Phase 2, Customer onboarding | `docs/architecture/phase5-meridian.md` and `evaluation/reports/phase5-gate/manifest.json` record the onboarding flow in a later repository phase. | contemporaneous direct evidence for delivery | Yes as a roadmap output | Same-author and fictional; no earlier phase-exit claim. |
| P31L1138 | Phase 3, Ingestion, Metadata, Embeddings, Vector indexing, Hybrid retrieval, Local inference, Citations | `docs/evaluation/phase3-method.md`, `evaluation/reports/phase3-gate/manifest.json`, `evaluation/reports/phase3-gate/pytest-real-ai-junit.xml` and `evaluation/reports/phase3/SUMMARY.md` record implemented and exercised capabilities. | contemporaneous direct evidence | Yes as capabilities | The original citation target remains unmet in the recorded Phase 3 runs. |
| P31L1138 | Phase 4, Incident extraction, Ticket drafting, Approval, State machine, External submission, Recovery | `docs/architecture/phase2-apex-slice.md`, `evaluation/reports/phase2-gate/manifest.json`, `docs/security/phase4-security-and-reliability.md` and `evaluation/failure-reports/phase4/fi-report.md` record the workflow and recovery with simulated external systems. | contemporaneous direct evidence | Yes within local/mock scope | Ticket approval is application evidence. |
| P31L1138 | Phase 5, Frontend, Document explorer, AI assistant, Incident explorer, Approval queue, Metrics | `docs/phase6/phase6-closure-gate.md` and `docs/phase6/phase6-review-report.md` record repository Phase 6 UI verification. | contemporaneous direct evidence | Yes as delivered UI | Human screen-reader review remains independent work. |
| P31L1138 | Phase 6, Tenant isolation, Authorization tests, Prompt-injection tests, Audit logging, Fault injection | `docs/security/phase4-security-and-reliability.md`, `evaluation/reports/phase4-gate/manifest.json`, `docs/phase7/phase7-gate.md` and `evaluation/failure-reports/phase7/fi-report.json` document those tests and controls across checkpoints. | contemporaneous direct evidence | Yes within the documented local scope | No independent safety acceptance inferred. |
| P31L1138 | Phase 6, Observability | `evaluation/observability/telemetry-summary.json` and `docs/operations/observability.md` show logs, metrics and spans. | contemporaneous direct evidence for telemetry, missing for the SDK/exporter | Yes as a roadmap capability | Separate OpenTelemetry register gaps remain owner-gated. |
| P31L1138 | Phase 7, Apex UAT, Meridian UAT, Requirements traceability, Acceptance reports | `evaluation/customer-acceptance/deterministic/uat-report.json`, `evaluation/customer-acceptance/real/uat-report.json`, `docs/traceability/requirements-traceability-matrix.json` and `docs/phase7/phase7-closure-gate.md` cover both UAT sets and traceability. | contemporaneous direct evidence | Yes for same-author UAT and its reports | Gate C independent acceptance remains missing separately. |
| P31L1138 | Phase 8, Retrieval benchmarks, Citation evaluation, Workflow benchmarks, Failure recovery | `docs/evaluation/phase8-heldout-report.md`, `docs/evaluation/phase8-heldout-disposition.md` and `evaluation/failure-reports/phase7/fi-report.json` record measured evaluations and simulated recovery. | contemporaneous direct evidence | Yes as evaluated outputs | Candidate promotion denied and separate AI targets remain unmet. |
| P31L1138 | Phase 8, Business workflow comparison | `evaluation/comparison/protocol.md` defines the comparison. `evaluation/demo-runs/20261113-150933-73e0/comparison/comparison.json` records measured automated time and empty observed and simulated manual classes. | contemporaneous direct evidence for automated measurements, missing for manual inputs | Partial | Human observation or a separately approved, clearly labelled simulated baseline. No productivity claim. |
| P31L1138 | Phase 9, Cloud-ready architecture | `docs/architecture/cloud-portability.md` describes AWS, Azure and Google Cloud mappings and prerequisites. | contemporaneous direct evidence | Yes as architecture | Design only, with deployment prerequisites recorded. No cloud deployment is part of this validation. |
| P31L1138 | Phase 9, Terraform/OpenTofu examples | `infrastructure/terraform/README.md`, `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` and `terraform.tfvars.example` in `infrastructure/terraform/`. | contemporaneous direct evidence | Yes as examples | Schema validation is evaluated in the next row. |
| P31L1138 | Phase 9, Local validation | [Terraform checkpoint](../../evaluation/terraform/provider-validation.md) records successful formatting, local provider-backed validation and schema inspection against AWS 5.100.0. | deterministic current validation | Yes, locally | Owner approved the exact package. The run used a filesystem mirror and disabled backend initialization. Deployment remains untested. |
| P31L1138 | Phase 9, Deployment tradeoffs | `docs/architecture/deployment-tradeoffs.md` and `docs/customer-delivery/09-architecture-tradeoff-record.md` give deployment choices and constraints. | contemporaneous direct evidence | Yes | Documentation scope. |
| P31L1138 | Phase 9, Optional Kubernetes examples | `infrastructure/kubernetes/eaop.yaml` and `tests/test_infrastructure_examples.py` provide and parse an illustrative manifest. | deterministic current validation | Yes at example level | Cluster execution is not applicable to the example criterion. The architecture document's “not built” note predates the example in `3e891e0`. The tracked example and parser resolve the artifact question at HEAD. |
| P31L1138 | Phase 10, README | `README.md` and `tests/test_readme_results.py` tie stated results to supporting artifacts. | deterministic current validation | Yes locally | Publication review is a separate step. |
| P31L1138 | Phase 10, Customer discovery documents | `docs/customer-discovery/README.md`, `docs/customer-discovery/apex-industrial.md`, `docs/customer-discovery/meridian-fleet.md` and `docs/customer-delivery/01-customer-discovery-summary.md` document fictional scenarios. | contemporaneous direct evidence | Yes within fictional scope | No real interviews are claimed. |
| P31L1138 | Phase 10, Architecture documentation | `docs/architecture/system-architecture.md` and `docs/architecture/diagrams.md`. | contemporaneous direct evidence | Yes locally | No deployment attestation inferred. |
| P31L1138 | Phase 10, Deployment runbook | `docs/operations/deployment-runbook.md` and `docs/operations/local-runbook.md`, with the isolated restore in `docs/operations/full-compose-backup-restore.md`. | deterministic current validation for proven local operations | Yes locally | Restore remains scoped to a disposable Compose project. |
| P31L1138 | Phase 10, Technical demonstration | `docs/customer-delivery/demonstration-27-steps.md`, `evaluation/demo-runs/20261113-152713-c19b/report.json` and `evaluation/clean-environment/20261113-183717`. | deterministic current validation for same-machine reproduction, missing for independent/external evidence | Yes for the demonstration deliverable | Gate C reviewer reproduction still required for full acceptance. |
| P31L1138 | Phase 10, Security review | [Candidate security disposition](phase-10-candidate-security-disposition.md) and its security evidence matrix. | contemporaneous direct evidence for the local review, deterministic current validation by runtime lineage, missing for independent review | Yes for the local review artifact | NOT READY for exit or release. Gate C, independent V41-14.02 acceptance and owner disposition are open. |
| P31L1138 | Phase 10, GitHub audit | `docs/planning/publication-handoff.md` records local preparations and repository-side procedures. | contemporaneous direct evidence for the handoff, missing for the GitHub audit | No | Hard owner and external release gate. Verify identity, permissions and publication scope on the authorized repository. |
| P31L1138 | Phase 10, Versioned release | `v4.1.0-local-rc1` and `docs/planning/final-completion-report.md` identify the local checkpoint. | contemporaneous direct evidence for the checkpoint, missing for release | No | Hard owner and external release gate. Need approved, tested published release evidence under Part 32 and Part 34. |

## P31L1229 · actions at each phase end

Original specification, lines 1229–1239.

```text
At the end of each phase:

1. Run applicable tests.
2. Fix failures.
3. Verify integration.
4. Review security.
5. Update documentation.
6. Commit validated changes with accurate metadata.
7. Record completed work and remaining limitations.

Do not stop at scaffolding.
```

| Requirement | Acceptance criterion | Existing evidence | Evidence quality | Satisfied? | Remaining gap |
|---|---|---|---|---|---|
| P31L1229 | Run applicable tests. | `evaluation/reports/phase2-gate/manifest.json`, `evaluation/reports/phase3-gate/manifest.json`, `evaluation/reports/phase4-gate/manifest.json`, `docs/security/phase5-closure-gate.md`, `docs/phase6/phase6-closure-gate.md`, `evaluation/reports/phase7-gate/manifest.json` and `docs/evaluation/phase8-heldout-report.md` record scoped runs. | contemporaneous direct evidence for stored runs, missing for Phase 1 and later exits | Partial | Phase 1 test source exists without a stored result. Phase 9 Terraform formatting and provider checks cover the local example. Complete Phases 9–10 exit runs are still outstanding. |
| P31L1229 | Fix failures. | `docs/security/phase4-security-and-reliability.md`, `docs/phase6/phase6-closure-gate.md` and `docs/phase7/phase7-gate.md` document fixes. `docs/evaluation/phase8-heldout-disposition.md` documents unmet thresholds and rejected promotion. | contemporaneous direct evidence where observed fixes or dispositions are recorded, missing for a complete phase-end trail | Partial | No applicable fix can be established for a run with no recorded failures. No inference that all failures were fixed in the uncovered phases. |
| P31L1229 | Verify integration. | `evaluation/reports/phase2-gate/manifest.json`, `evaluation/reports/phase3-gate/pytest-real-ai-junit.xml`, `evaluation/reports/phase4-gate/pytest-real-ai-junit.xml`, Phases 5–7 gate records listed above, and Phase 8 frozen reports support scoped integration. `docs/planning/final-validation-report.md` covers later local integration. | contemporaneous direct evidence for phase runs, deterministic current validation for the later regression, missing for other exits | Partial | No Phase 1 exit integration record. The Phase 9 example passed local schema validation. Phase 10 release-candidate and remote integration checks remain outstanding. |
| P31L1229 | Review security. | `docs/security/phase4-security-and-reliability.md`, `docs/security/phase5-closure-gate.md`, `docs/phase6/phase6-closure-gate.md` and `docs/phase7/phase7-closure-gate.md` record scoped reviews. `docs/evaluation/phase8-heldout-disposition.md` records AI safety findings. | contemporaneous direct evidence for the scoped reviews, retrospective reconstruction for the early crosswalk, missing for uncovered exits | Partial | No Phase 1, 2 or 3 end-of-phase security review located. Phase 8 safety findings have limited scope. The [candidate disposition](phase-10-candidate-security-disposition.md) records the Phase 10 local review. A complete Phase 9 exit review and final Phase 10 exit evidence remain outstanding. |
| P31L1229 | Update documentation. | Phase-linked material in `CHANGELOG.md`, `docs/architecture/phase2-apex-slice.md`, `docs/evaluation/phase3-method.md` and the stored gate records. Later artifacts include cloud and tradeoff docs, the publication handoff and local runbook. | contemporaneous direct evidence for dated updates, retrospective reconstruction for this consolidation | Partial | Later documents improve coverage. A final Phase 9/10 exit record remains open. |
| P31L1229 | Commit validated changes with accurate metadata. | Foundation `d24f4ba`, Phase 2 `306a317`, Phase 3 `a842c37`, Phase 4 `44b1083`/later closure `6d9217d`, Phase 5 `9f6b667`, Phase 6 `b911fbf`, Phase 7 `d8a8f82` and Phase 8 `0f9c954` are inspectable. `docs/planning/provenance-exceptions.json` records historical metadata failures. | contemporaneous direct evidence for commits, deterministic current validation for provenance scan, missing for uncovered validation or exit commits | Partial | Foundation metadata alone cannot prove testing. Preserve PROV-01. There is no validated final Phase 9/10 release exit commit. |
| P31L1229 | Record completed work and remaining limitations. | `d24f4ba:CHANGELOG.md`, Phases 2–7 notes and manifests, `docs/evaluation/phase8-heldout-disposition.md` and `docs/planning/final-validation-report.md` record work and limitations. | contemporaneous direct evidence for checkpoint records, retrospective reconstruction for this audit | Partial | A dated consolidation cannot establish missing contemporaneous actions. Final Phase 9/10 dispositions remain to be recorded. |
| P31L1229 | Do not stop at scaffolding. | Phase 2–8 working evidence above and `docs/planning/final-validation-report.md`. Phase 1 foundation files and Phase 9 examples exist. | contemporaneous direct evidence for working increments, deterministic current validation for integrated local results, missing for completed external exits | Partial | Working local software is demonstrated. Complete Phase 9/10 exits are outstanding. |

## Traceability and gates

The original roadmap links `docs/phase6/phase6-closure-gate.md`, `docs/phase7/phase7-gate.md`, `docs/phase7/phase7-closure-gate.md` and `docs/evaluation/phase8-heldout-disposition.md`. Catalogue R32.1 contributes `tests/test_traceability.py` and `evaluation/reports/phase7-gate/manifest.json`. The traceability test validates the mapping and the manifest records the stated Phase 7 checks.

The phase-end register links `docs/phase6/phase6-closure-gate.md`, `docs/phase7/phase7-gate.md`, `docs/evaluation/phase8-heldout-report.md` and `docs/planning/retrospective-phase-gates-1-4.md`. `tests/test_retrospective_phase_gates.py` checks scope, paths and labelling. It provides deterministic current validation of that document. Phase 2–4 audit source paths and individual Git references are listed in the retrospective record, including the stored JUnit evidence. The amended register adds the relevant later gate and exit-evidence paths.

The historical register labels L1229 “complete” in its phase field while its status is Partial. The phase field is a scheduling label and provides no evidence of completion. The criteria here follow the original specification.

| Basis | Required record | Evidence quality | Disposition |
|---|---|---|---|
| Part 31 L1229–1239 and Part 34 execution rules | Evidence that the required actions happened at the applicable phase end. Part 31 names no universal approval form, signature or independent reviewer. | missing for uncovered historical actions, not applicable for a universal Part 31 signature | A separate retrospective document cannot fill Phase 1 test, integration or security gaps or the missing Phase 2–3 security reviews. The repository establishes that no such records are stored in the artifacts inspected. It cannot establish whether unrecorded actions happened. |
| `docs/planning/accelerated-gap-closure-plan.md` §§8–11 and `docs/evaluation/phase8-heldout-disposition.md` | Separate authorization to start Phase 9 execution after Phase 8. | contemporaneous direct evidence for the recorded negative disposition, missing for a superseding authorization | Phase 8 evidence was accepted **for review**. Candidate promotion and further optimization were denied and Phase 9 was not yet approved. Phase 9 artifacts were subsequently committed. The owner subsequently authorized the exact AWS provider and the prospective local validation recorded above. A formal Phase 9 exit remains unrecorded. |
| `docs/security/phase5-closure-gate.md`, `docs/phase6/phase6-closure-gate.md`, `docs/phase7/phase7-gate.md`, `docs/phase7/phase7-closure-gate.md` | Local technical gate results for their stated scopes. Earlier Gate A concerned entry to Phase 8. | contemporaneous direct evidence | Recorded local results, with no independent or blanket owner sign-off established. They supersede the broad register claim that Phases 1–8 all executed under approval gates. |
| `docs/planning/progress-tracker.md` and `docs/customer-delivery/independent-review-package.md` | Gate B reproduction and Gate C independent reproduction/acceptance for full completion, with owner disposition after review. | deterministic current validation for same-machine Gate B, missing for Gate C | Gate B passed on the same machine. Gate C, independent V41-14.02 and human screen-reader review remain open. No accepted owner assertion or independent/external result fills these gaps. |
| Parts 2, 32, 33 and 34, `docs/planning/publication-handoff.md` | Explicit owner authorization for identity/repo actions, CI, publication and release. Account and repository audit, green CI and tested release records. | missing for authorization and external records | Hard release blockers. Local handoff and tag prove preparation and a checkpoint. Publication and any versioned release need affirmative, separately recorded authority. |

P31L1138 remains **Partial** because of incomplete roadmap outputs, including GitHub identity and CI, the business comparison, Phase 10 GitHub audit and release. The Phase 10 local security review is documented. P31L1229 remains **Partial** because the evidence does not cover the required phase-end actions across all phases. The old closure plan's “Gate notes exist” was a documentation milestone. The retrospective record supports that milestone and leaves historical evidence missing. Missing records cannot be recreated as historical proof. New gates can be recorded for future execution. A documented owner deviation would be a separate disposition with the original evidence gap preserved.

## Remaining closure map

The [closure plan](requirement-closure-plan.json) contains **36 open requirements**. Each ID appears once in the primary column below. The gate and release implications describe overlaps. Here “release-blocking” means blocking a claim of full V4.1 acceptance or an authorized, tested V4.1 release under the current handoff. The [accelerated plan](accelerated-gap-closure-plan.md) defines full completion as Verified coverage or explicit owner-approved deviations plus independent reproduction and the authorized publication chain.

| Primary category | Remaining IDs | Gate and release implications |
|---|---|---|
| Locally closable | None with a demonstrated standalone closure path | The local candidate-specific Phase 10 review is recorded. Their rollups still need external or historical evidence. |
| Owner-gated | P5L313, P21L796, P22L815 (3) | OpenTelemetry dependencies (two entries) and actual comparison inputs (human observer or an approved simulation disposition). Required scope must be evidenced or explicitly dispositioned for full acceptance. L815 says “where practical”. |
| Independent-review required | P13L512, P13L515, P13L517, P14L536, P18L659, P21L769, P21L770, P23L856, P32L1277 (9) | Gate C reproduction (two IDs), numeric-safety acceptance and screen-reader audit. Five AI entries also depend on owner authorization and fresh independent labels. Independent results alone may still fail the quality criteria. |
| Remote CI/publication required | P1L14, P2L39, P5L319, P27L968, P31L1138, P32L1261, P32L1274, P32L1275, P32L1276, P33L1282, P34L1349, P34L1362, P34L1363, P34L1395 (14) | Owner-gated. Direct release chain: identity, repository permissions and audit, green CI, explicit publication consent, tested versioned release. P1L14, P31L1138 and P34L1395 are rollups also carrying their local or phase dependencies. |
| Historical evidence limitation | P2L54, P2L71, P31L1229, P32L1272, P32L1273, P33L1303, P34L1322, P34L1389 (8) | Six PROV-01 IDs plus historical phase-process evidence under P31L1229 and P34L1322. Keep exceptions and evidence gaps recorded. P31L1229 also requires future exit actions. Unqualified full acceptance needs explicit owner disposition where evidence cannot be recovered. Preserve history and tag. |
| Optional/non-release-blocking | P13L511, P23L835 (2) | Optional reranker and optional broker/monitoring adoption. Keep current statuses and stated limits. The Kubernetes example already exists and is outside the open set. |
| Genuinely unresolved engineering defect | No standalone ID assigned here | REL-01 is a real open intermittent readiness defect in `docs/planning/reliability-defect-register.md`, cutting across demonstration reproduction. Its cause remains unknown. The unmet AI targets are measured gaps under the independent-review group. The accepted regression gave no new application regression. |

**Next workstream.** Arrange independent Gate C reproduction and V41-14.02 acceptance using the existing reviewer package. **Recommended effort: medium.**
