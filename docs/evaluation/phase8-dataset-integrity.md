# Phase 8 dataset and label integrity report (eval-v2.0)

Source: `evaluation/phase8/validate_dataset.py` and `evaluation/datasets/eval-v2/validation_report.json`; freeze commit `c0d19c9`.

**Validation result: 0 problems.** Evidence spans verified verbatim through the application's own parsers: 187.

## Composition

- Passages: {'apex': {'total': 735, 'current': 717}, 'meridian': {'total': 712, 'current': 694}}
- Queries: 215 (152 answerable; 51 refusal expected; 12 adversarial-injection with optional answer)
- By category: {'keyword': 28, 'paraphrase': 35, 'multi_hop': 22, 'version_conflict': 18, 'conflicting_record': 8, 'compare': 13, 'asset_confusion': 14, 'procedure': 14, 'adversarial_injection': 12, 'unanswerable': 51}
- By tag (categories overlap): {'hard_negative': 139, 'paraphrase': 35, 'multi_relevant': 35, 'multi_document': 35, 'version_conflict': 18, 'conflicting_record': 8, 'similar_identifiers': 14, 'semantic': 14, 'adversarial': 28, 'prompt_injection': 16, 'unanswerable': 51, 'undocumented': 12, 'nonexistent_id': 8, 'gap_in_manual': 9, 'other_tenant_only': 8, 'cross_tenant': 8, 'outside_domain': 6, 'approval_bypass': 4, 'direct_injection': 4}
- Multi-relevant: 35; hard-negative queries: 114; adversarial or cross-tenant queries: 28; version-conflict: 18; difficulty: {'medium': 103, 'easy': 8, 'hard': 104}
- By split and tenant: {'challenge/apex': 13, 'challenge/meridian': 9, 'dev/apex': 57, 'dev/meridian': 61, 'test/apex': 47, 'test/meridian': 28}
- Incident cases: {'total': 60, 'by_tenant': {'apex': 30, 'meridian': 30}, 'by_split': {'dev': 34, 'challenge': 6, 'test': 20}, 'by_tag': {'clear': 28, 'severity': 8, 'ambiguous': 8, 'safety': 4, 'unregistered_asset': 4, 'no_asset': 4, 'prompt_injection': 4, 'adversarial': 4}}

## Frozen split hashes

| Split | Queries | Incident cases | SHA-256 |
|---|---|---|---|
| challenge | 22 | 6 | `7d18b6bc9fe7697114fea6b2d36d18bca38dc8e4d934a4fb0fea01bbf85a5096` |
| dev | 118 | 34 | `623b612bef23475cfd6bdb3ac52233bb8773aae8fc1b8ccf40b5cf0ddd138986` |
| test | 75 | 20 | `19540a5c88eb7943a640f0fb802de6f40612c32a70e0a58c1ac4af2cb3e6893a` |

## Leakage and duplicate checks

{'max_cross_split_query_jaccard': 0.846, 'exact_duplicate_queries': 0, 'groups_spanning_splits': 0}. No scenario group spans two splits; no exact duplicate query within a tenant; identical wording across tenants occurs only where the same question is deliberately asked of both (isolation probes) and those items share a split.
Regeneration from the seed is byte-identical (`tests/test_phase8_dataset_integrity.py`).

## Label limitations

Labels are author-generated before any model run; no independent reviewer has reviewed them (worksheet: `phase8-label-review-sample.md`, 28 stratified items). No AI second pass was performed. Deterministic consistency checks only: references resolve, evidence spans exist, required facts occur in evidence, forbidden facts do not.
Known label questions: the two 'answer from memory' direct-injection prompts; priority labels restate the documented policy independently, so priority accuracy mixes category extraction, signal extraction and rule application.
