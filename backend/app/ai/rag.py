"""Evidence-grounded question answering with citation verification."""
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai.asset_references import reference_spans, resolve_references, supports_referenced_interval
from app.ai.authority import apply_authority_order
from app.ai.coolant_alarms import unsupported_coolant_alarm
from app.ai.embeddings import Embedder
from app.ai.inspection_applicability import unsupported_inspection_observation
from app.ai.llm import CitedQuote, LLMAnswer, LLMClient, LLMOutputInvalid, Passage
from app.ai.safeguards import (
    IDENTIFIER,
    _numbers,
    check_answer_support,
    unsupported_identifiers,
    unsupported_numbers,
    verify_citation_sources,
)
from app.ai.safety import looks_like_override
from app.ai.service_intervals import unsupported_whole_unit_interval
from app.ai.specification_conflicts import has_authoritative_conflict
from app.ai.suppression import suppress_low_authority
from app.ai.tuning import get_tuning
from app.observability.metrics import METRICS
from app.retrieval.entities import required_entities, resolve_models, text_names_entity
from app.retrieval.search import Hit, search, split_question
from app.retrieval.text import normalize_ws, sentences, tokens

INSUFFICIENT = "Insufficient evidence in the available documents to answer this question."
MIN_OVERLAP = 0.34
MAX_CONTEXT_PASSAGES = 4

# A citation suffix after two complete scalar claims. Other bracketed lists may be technical data.
_VALVE_OPENING = r"has a discharge valve opening of (?:about )?[0-9]+(?:\.[0-9]+)?(?: percent| ?%)"
_VALVE_COMPARISON = re.compile(
    rf"The (?P<first>{IDENTIFIER.pattern}) {_VALVE_OPENING}, while "
    rf"the (?P<second>{IDENTIFIER.pattern}) {_VALVE_OPENING} "
    r"(?P<marker>\[(?P<left>[0-9]+), ?(?P<right>[0-9]+)\])\.?"
)


@dataclass
class AnswerResult:
    answer: str
    grounded: bool
    insufficient_evidence: bool
    citations: list[dict] = field(default_factory=list)
    excluded_suspicious: list[str] = field(default_factory=list)
    llm_backend: str = ""
    llm_model: str = ""
    embedding_backend: str = ""
    problems: list[str] = field(default_factory=list)


def has_evidence(hit: Hit, embedder: Embedder) -> bool:
    if hit.similarity >= embedder.evidence_threshold:
        return True
    return embedder.lexical_gate and hit.overlap >= MIN_OVERLAP


def snap_quote(quote: str, passage_text: str, min_overlap: float = 0.6) -> str | None:
    """E7: the verbatim sentence of the SAME passage that best matches a non-verbatim quote (None if no sentence matches well).

    The claim itself is still verified separately against the full cited passage (numbers, identifiers), so snapping only repairs the
    evidence quotation; it can never introduce text that is not in a retrieved passage of the same tenant."""
    wanted = set(tokens(quote))
    if not wanted:
        return None
    best, best_score = None, 0.0
    for sentence in sentences(passage_text):
        score = len(wanted & set(tokens(sentence))) / len(wanted)
        if score > best_score:
            best, best_score = sentence, score
    if best is None or best_score < min_overlap or normalize_ws(best) not in normalize_ws(passage_text):
        return None
    return best


def complete_citations(llm_answer: LLMAnswer, usable: list[Hit], valid: list[int], question: str,
                       entity_sets: list[set[str]], *,
                       reference_spans: tuple[tuple[int, int], ...] = ()) -> list[int]:
    """C3: attach, as verbatim-sentence citations, the context passages that actually contain a number or identifier the answer states.

    Only passages that were retrieved and given to the model for this question are eligible, and only if the question names no entity or the passage names at
    least one of them; the claim itself must be present in the passage text, so nothing is added that the evidence does not contain."""
    cited_texts = [usable[i - 1].text for i in valid]
    missing_numbers = unsupported_numbers(llm_answer.text, cited_texts, reference_spans=reference_spans)
    missing_ids = unsupported_identifiers(llm_answer.text, cited_texts, question)
    if not missing_numbers and not missing_ids:
        return valid
    valid = list(valid)
    for token in [*missing_numbers, *(i for i in missing_ids)]:
        for index, hit in enumerate(usable, start=1):
            if index in valid:
                continue
            has_token = token in _numbers(hit.text) or token.upper() in hit.text.upper()
            if not has_token or (entity_sets and not any(text_names_entity(hit.text, alts) for alts in entity_sets)):
                continue
            sentence = next((x for x in sentences(hit.text) if token in _numbers(x) or token.upper() in x.upper()), None)
            if sentence is None or normalize_ws(sentence) not in normalize_ws(hit.text):
                continue
            llm_answer.cited.append(CitedQuote(index, sentence))
            valid.append(index)
            break
    return valid


def select_context(usable: list[Hit], k: int, diverse: bool) -> list[Hit]:
    """E5: at most k passages; when diverse, prefer one passage per document before filling with further passages of the same documents."""
    if not diverse:
        return usable[:k]
    chosen, seen = [], set()
    for h in usable:
        if h.document_id not in seen:
            chosen.append(h)
            seen.add(h.document_id)
        if len(chosen) == k:
            return chosen
    for h in usable:
        if len(chosen) < k and h not in chosen:
            chosen.append(h)
    return chosen


def verify_citations(llm_answer: LLMAnswer, passages: list[Passage]) -> tuple[list[int], list[str]]:
    """Return (valid cited indexes, problems). A citation is valid only if it points at a retrieved
    passage AND its quote appears verbatim (whitespace-normalized) in that passage."""
    by_index = {p.index: p for p in passages}
    problems: list[str] = []
    valid: list[int] = []
    for cited in llm_answer.cited:
        passage = by_index.get(cited.index)
        if passage is None:
            problems.append(f"citation [{cited.index}] does not reference a retrieved passage")
        elif not cited.quote.strip() or normalize_ws(cited.quote) not in normalize_ws(passage.text):
            snapped = snap_quote(cited.quote, passage.text) if get_tuning().quote_snap and cited.quote.strip() else None
            if snapped is None:
                problems.append(f"citation [{cited.index}] quote not found in the cited passage")
            else:
                cited.quote = snapped  # E7: replaced by a verbatim sentence of the same cited passage
                valid.append(cited.index)
        else:
            valid.append(cited.index)
    if get_tuning().citation_marker_formats:
        from app.ai.safeguards import citation_marker_indexes
        markers = citation_marker_indexes(llm_answer.text)
    else:
        markers = {int(m) for m in re.findall(r"\[(\d+)\]", llm_answer.text)}
    for marker in markers - set(valid):
        problems.append(f"answer marker [{marker}] has no verified citation")
    return valid, problems


def _verified_comparison_marker(llm_answer: LLMAnswer, valid: list[int]) -> tuple[
    tuple[tuple[int, int], ...], list[str],
]:
    """Recognize the trailing citation pair in a two-model valve-opening comparison."""
    comparison = _VALVE_COMPARISON.fullmatch(llm_answer.text.rstrip())
    if comparison is None:
        return (), []
    models = comparison.group("first", "second")
    indexes = comparison.group("left", "right")
    if models[0] == models[1] or indexes[0] == indexes[1]:
        return (), []

    # Match the two references to the model subjects in the already verified structured quotes.
    verified = {str(cited.index): cited.quote for cited in llm_answer.cited if cited.index in valid}
    problems = [f"answer marker [{index}] has no verified citation" for index in indexes if index not in verified]
    if problems:
        return (), problems
    if any(
        IDENTIFIER.findall(verified[index]) != [model] or "discharge valve" not in verified[index].lower()
        for model, index in zip(models, indexes, strict=True)
    ):
        return (), []
    return (comparison.span("marker"),), []


def combine_parts(results: list[AnswerResult]) -> AnswerResult:
    """One answer from per-part answers. Grounded only if every part is grounded; otherwise the first non-grounded part decides the outcome (refusal if every part refused),
    so a half-answered question is never presented as answered. Citation markers of later parts are renumbered after the earlier ones."""
    first = results[0]
    meta = {"llm_backend": first.llm_backend, "llm_model": first.llm_model, "embedding_backend": first.embedding_backend}
    problems = [p for r in results for p in r.problems]
    excluded = [e for r in results for e in r.excluded_suspicious]
    if not all(r.grounded for r in results):
        if all(r.insufficient_evidence for r in results):
            return AnswerResult(INSUFFICIENT, grounded=False, insufficient_evidence=True, excluded_suspicious=excluded, problems=problems, **meta)
        bad = next(r for r in results if not r.grounded)
        return AnswerResult(bad.answer, grounded=False, insufficient_evidence=False, excluded_suspicious=excluded, problems=problems or ["part of the question could not be answered with verified evidence"], **meta)
    texts, citations, offset = [], [], 0
    for r in results:
        texts.append(re.sub(r"\[(\d+)\]", lambda m, o=offset: f"[{int(m.group(1)) + o}]", r.answer))
        citations += [{**c, "marker": c["marker"] + offset} for c in r.citations]
        offset += len(r.citations)
    return AnswerResult(" ".join(t.strip() for t in texts), grounded=True, insufficient_evidence=False, citations=citations, excluded_suspicious=excluded, problems=[], **meta)


def answer_question(session: Session, tenant_id, question: str, embedder: Embedder, llm: LLMClient,
                    *, kinds: list[str] | None = None, enforce_entities: bool = True) -> AnswerResult:
    """Retrieve, ask the model, verify; records the outcome class (no question text or answer text is recorded)."""
    parts = split_question(question) if get_tuning().decompose_answers else [question]
    if len(parts) > 1:
        result = combine_parts([
            _answer_question(session, tenant_id, part, embedder, llm, kinds=kinds, enforce_entities=enforce_entities,
                             original_question=question)
            for part in parts
        ])
    else:
        result = _answer_question(session, tenant_id, question, embedder, llm, kinds=kinds, enforce_entities=enforce_entities)
    outcome = "grounded" if result.grounded else "insufficient_evidence" if result.insufficient_evidence else "withheld"
    METRICS.incr("ai_answers_total", tenant=str(tenant_id), outcome=outcome)
    return result


def _answer_question(session: Session, tenant_id, question: str, embedder: Embedder, llm: LLMClient,
                     *, kinds: list[str] | None = None, enforce_entities: bool = True,
                     original_question: str | None = None) -> AnswerResult:
    tun = get_tuning()
    meta = {"llm_backend": llm.name, "llm_model": llm.model, "embedding_backend": embedder.name}
    if tun.query_override_gate and looks_like_override(question):
        return AnswerResult(INSUFFICIENT, grounded=False, insufficient_evidence=True,
                            problems=["the question tries to override the evidence, tenant or approval rules"], **meta)
    hits = search(session, tenant_id, question, embedder, k=8, kinds=kinds)
    excluded = [h.chunk_id for h in hits if h.suspicious]
    candidates = [h for h in hits if not h.suspicious and has_evidence(h, embedder)]
    if tun.authority_demotion:
        candidates = apply_authority_order(candidates)
    usable = select_context(candidates, tun.context_k, tun.context_diverse)
    if tun.low_authority_suppression:
        usable = suppress_low_authority(usable, lambda ids: resolve_models(session, tenant_id, ids))
    if not usable:
        return AnswerResult(INSUFFICIENT, grounded=False, insufficient_evidence=True,
                            excluded_suspicious=excluded, **meta)

    passages = [Passage(index=i, chunk_id=h.chunk_id, text=h.text) for i, h in enumerate(usable, start=1)]
    try:
        with METRICS.timer("llm_seconds", tenant=str(tenant_id), kind="answer", backend=llm.name):
            llm_answer = llm.answer(question, passages)
    except LLMOutputInvalid as exc:
        METRICS.incr("llm_invalid_output_total", tenant=str(tenant_id), kind="answer")
        return AnswerResult("The model's output was not valid and was withheld.", grounded=False,
                            insufficient_evidence=False, excluded_suspicious=excluded,
                            problems=[f"llm output invalid: {exc}"], **meta)
    valid, problems = verify_citations(llm_answer, passages)
    if not llm_answer.text.strip():
        return AnswerResult(INSUFFICIENT, grounded=False, insufficient_evidence=True,
                            excluded_suspicious=excluded, **meta)
    # Decomposed answers currently renumber single markers only.
    marker_spans = ()
    if not problems and original_question is None:
        marker_spans, problems = _verified_comparison_marker(llm_answer, valid)
    if problems or not valid:
        return AnswerResult("The generated answer could not be verified against the source documents "
                            "and was withheld.", grounded=False, insufficient_evidence=False,
                            excluded_suspicious=excluded, problems=problems or ["no verified citations"],
                            **meta)
    references = {}
    if tun.question_asset_id_exemption and enforce_entities and tun.entity_gate:
        references = resolve_references(session, tenant_id, original_question or question, llm_answer.text)
    spans = reference_spans(llm_answer.text, references) if references else ()
    numeric_spans = spans + marker_spans
    # Coolant alarm binding uses the verified quotes supplied with the answer.
    verified_quote_count = len(llm_answer.cited)
    if tun.claim_completion:
        valid = complete_citations(llm_answer, usable, valid, question, required_entities(session, tenant_id, question),
                                   reference_spans=numeric_spans)
    cited_texts = [usable[i - 1].text for i in valid]
    problems = check_answer_support(llm_answer.text, cited_texts, question, reference_spans=numeric_spans)
    citations = []
    for cited in llm_answer.cited:
        hit = usable[cited.index - 1]
        citations.append({
            "marker": cited.index, "chunk_id": hit.chunk_id, "document_id": hit.document_id,
            "filename": hit.filename, "version": hit.version, "page_number": hit.page_number,
            "record_id": hit.record_id, "quote": cited.quote,
        })
    problems += verify_citation_sources(session, tenant_id, citations)
    if not problems and enforce_entities and unsupported_coolant_alarm(
        question, llm_answer.text, llm_answer.cited[:verified_quote_count], usable,
    ):
        problems.append("the cited evidence does not bind the coolant temperature alarm threshold to the requested model")
    if not problems and enforce_entities and unsupported_whole_unit_interval(
        question, llm_answer.text, llm_answer.cited, usable,
    ):
        problems.append("the cited evidence does not bind the whole-unit service interval to the requested model")
    if not problems and enforce_entities and unsupported_inspection_observation(
        original_question or question, llm_answer.text, llm_answer.cited, usable,
    ):
        problems.append("the cited inspection evidence does not bind the reading to the requested asset and period")
    if not problems and enforce_entities and tun.entity_gate:
        missing = [sorted(a)[0] for a in required_entities(session, tenant_id, question)
                   if not any(text_names_entity(t, a) for t in cited_texts)]
        if missing:  # E8: an identifier named in the question is absent from every cited passage (e.g. a sibling model's page)
            return AnswerResult(INSUFFICIENT, grounded=False, insufficient_evidence=True, excluded_suspicious=excluded,
                                problems=[f"identifier(s) named in the question not found in the cited evidence: {', '.join(missing)}"], **meta)
    if not problems and spans and unsupported_numbers(llm_answer.text, cited_texts,
                                                      reference_spans=marker_spans):
        if not supports_referenced_interval(llm_answer.text, references, llm_answer.cited, usable):
            problems.append("the copied asset reference lacks a supporting maintenance interval in the cited manual")
    if not problems and enforce_entities and tun.authoritative_spec_conflict and has_authoritative_conflict(
        session, tenant_id, question, original_question or question, llm_answer.text, llm_answer.cited, usable,
    ):
        problems.append("the cited unverified specification conflicts with the current manual for the registered model")
    if problems:
        return AnswerResult("The generated answer contained claims not supported by the cited evidence and "
                            "was withheld.", grounded=False, insufficient_evidence=False,
                            excluded_suspicious=excluded, problems=problems, **meta)
    return AnswerResult(llm_answer.text, grounded=True, insufficient_evidence=False, citations=citations,
                        excluded_suspicious=excluded, **meta)
