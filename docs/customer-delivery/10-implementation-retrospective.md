# 10. Implementation retrospective

Honest account of the build, for the fictional customers and the project owner. Evidence is same-author; no real customer used the system.

## What worked
* Starting from one end-to-end slice (Apex), then adding Meridian through configuration, kept the design honest: Meridian required no change to shared code.
* Database-level isolation (forced row-level security) caught mistakes that application filters would have hidden; tests deliberately bypass the application filters to prove it.
* Treating failure paths as first-class (outbox, idempotency keys, durable ingestion jobs, fenced leases, fault injection FI-01 to FI-10) produced recoverable behaviour that tests exercise, including crashes, replays and races.
* Additive migrations with refuse-to-downgrade guards protected data and made batch-by-batch evidence possible.

## What did not work first time (and what changed)
* **Numeric safety.** Three live acceptance rounds (V5 to V7) failed because free-text and model-extracted numbers could not be trusted to drive priority. The architecture was changed so numbers from free text are unverified candidates and only signed fixtures or human verification can affect priority. The formal acceptance (V41-14.02) remains partial and the earlier failed evidence is preserved, not rewritten.
* **A deletion policy reversed by a sync (Batch 11A).** A changed upstream record recreated a document the customer had deleted. Found in review, fixed in the follow-up: deletions are now permanent tombstones.
* **Concurrent identical uploads (Batch 9).** The first job implementation answered 503 where the old contract answered `201 duplicate`; the fault-injection test caught it and the contract was restored.
* Several live checkpoint runs failed on defects in the checkpoint scripts themselves (case-sensitive header checks, an over-broad assertion, a harness race with the backup snapshot). They are kept in `evaluation/demo-runs/` and described in the batch reports.

## Measured limits (not met)
Citation correctness 89.8% on the held-out split against a 95% target; grounded-answer coverage 59.3%; raw model structured validity 90% on the held-out split; a large share of incidents is routed to human review (by design, and a cost). These results are preserved from Phase 8 and were not tuned against.

## Open at handover
V41-14.02 formal acceptance; REL-01 intermittent start-up stall; distributed rate limiting; container images and cloud deployment; UI for connectors and webhooks; independent reproduction; AI-quality targets. See [../planning/progress-tracker.md](../planning/progress-tracker.md).

## What I would do next
Independent reproduction on a clean machine; a connector and webhook management UI; a bounded REL-01 investigation; container images once base-image pulls are approved; AI-quality work on fresh independent confirmation data.
