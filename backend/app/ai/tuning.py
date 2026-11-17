"""Switchable quality settings for the Phase 8 experiments.

Every default reproduces the validated baseline behaviour exactly; an experiment turns one setting on through the
`EAOP_TUNING` environment variable (a JSON object) so it can be evaluated, compared and rolled back without code changes.
Unknown keys are rejected so a typo cannot silently run the baseline. The canonical JSON of the effective settings is hashed
and recorded in every run manifest.
"""
import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class Tuning:
    # E1 retrieval: embed "<kind> <file name>: <text>" instead of the bare text (stored text and quotes are unchanged)
    index_prefix: bool = False
    # E2 fusion: score = w_vec / (rrf_k + vector rank) + w_text / (rrf_k + text rank)
    rrf_k: int = 60
    w_vec: float = 1.0
    w_text: float = 1.0
    # E3 identifier handling: boost passages naming the query's model/asset identifiers (assets resolved to models via the register)
    entity_boost: float = 0.0
    # E4 rule-based splitting of multi-part questions into sub-queries merged by rank fusion
    subquery_split: bool = False
    # E5 context assembly
    context_k: int = 4
    context_diverse: bool = False
    # E6 answer prompt variant ("3" is the baseline)
    prompt_variant: str = "3"
    # E7 snap a non-verbatim quote to the best-matching verbatim sentence of the same cited passage
    quote_snap: bool = False
    # C1 (evidence-driven corrective change, not one of E1-E10): citation markers written as ranges or lists ([1-3], [1, 2]) are recognised as
    # citations, so their digits are not verified as numeric claims and every referenced citation index must be verified
    citation_marker_formats: bool = False
    # C3 (evidence-driven, priority 3 "citation-to-claim mapping"): when the answer states a number/identifier that is absent from the cited passages
    # but present in another passage that was given to the model for this question, cite that passage (with a verbatim sentence) instead of withholding
    claim_completion: bool = False
    # E8 refuse when an identifier named in the question is not present in any cited passage
    entity_gate: bool = False
    # E8b (part of the abstention work): refuse questions that try to override the evidence rules, tenant boundary or approval workflow
    query_override_gate: bool = False
    # C2 deterministic ranking: ties in the fused score are broken by stable keys so repeated runs (and fresh ingestions) rank identically
    stable_ranking: bool = False
    # E9 feature reranker over the top candidates using existing embeddings and lexical features (no new weights)
    rerank: bool = False
    rerank_depth: int = 20
    rerank_weights: tuple = (1.0, 0.5, 0.5, 0.2, 0.1)  # similarity, lexical overlap, identifier match, title match, original-rank prior
    # Priority 1: numeric measurements must be traceable to the report text; unsupported values are not used and force review
    numeric_verification: bool = False
    # D1 (evidence-driven, from the dev failure taxonomy: 12 of 27 dev failures are two-part questions): a question that splits into several parts is answered part by part, each part
    # with its own retrieval, answer and verification; the combined answer is grounded only if EVERY part is grounded (no partial answers), with citation markers renumbered
    decompose_answers: bool = False
    # H1 (dev failure taxonomy: 5 conflicting_record queries answered from an unverified note): passages that label themselves unverified are ordered
    # behind unmarked passages about the same subject before context selection; unchanged when no such higher-authority passage was retrieved
    authority_demotion: bool = False
    # H2 (H1 rejected: reordering cannot change membership): a structured service/incident note that declares itself unverified is removed from the
    # generation context when its asset resolves to one model and an authoritative same-model manual passage on the same topic is also in the context
    low_authority_suppression: bool = False
    # H3: omit digits inside a copied, uniquely registered asset reference from QA numeric verification.
    question_asset_id_exemption: bool = False
    # QA: withhold a comparable unverified specification that conflicts with the current model manual.
    authoritative_spec_conflict: bool = False
    # E10 incident extraction
    category_cross_check: bool = False  # model category disagreeing with the deterministic keyword rules routes to review
    # "raw" (baseline) | "model_category" (adds the equipment model id) | "asset_context" (adds the asset's own register name, e.g. its equipment family;
    # introduced after the guidance diagnosis showed the baseline query is equipment-blind)
    guidance_query: str = "raw"


_CACHE: dict[str, Tuning] = {}


def get_tuning() -> Tuning:
    raw = os.environ.get("EAOP_TUNING", "").strip()
    if raw not in _CACHE:
        data = json.loads(raw) if raw else {}
        known = {f.name for f in fields(Tuning)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown EAOP_TUNING keys: {sorted(unknown)}")
        if "rerank_weights" in data:
            data["rerank_weights"] = tuple(data["rerank_weights"])
        _CACHE[raw] = Tuning(**data)
    return _CACHE[raw]


def tuning_hash(t: Tuning | None = None) -> str:
    t = t or get_tuning()
    config = asdict(t)
    if not t.question_asset_id_exemption:
        # Preserve the recorded hashes for settings with H3 disabled.
        del config["question_asset_id_exemption"]
    if not t.authoritative_spec_conflict:
        del config["authoritative_spec_conflict"]
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def is_default(t: Tuning | None = None) -> bool:
    return (t or get_tuning()) == Tuning()
