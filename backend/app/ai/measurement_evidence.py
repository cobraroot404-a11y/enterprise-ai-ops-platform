"""Deterministic measurement evidence (V41-14.02, hardening V5).

A number proposed by the model (or by a regex) is only a *proposal*. It becomes a VERIFIED measurement when the report itself contains an identifiable
observation of that quantity, for the incident's own asset, in a compatible unit, in a current-observation context (not a threshold, a historical or
reference figure, or instruction text), with no contradicting current reading. Every decision carries its evidence span and location, or a reason.

Pipeline: split the report into sentences and clauses; find unit-bearing numbers per measurement type (units and supported conversions are explicit
tables); classify each candidate's context from the words around it; attribute it to an asset (nearest asset named before it in the sentence, else the
nearest after; a sentence naming no asset is attributed to the incident asset only when the report names a single asset); then decide per measurement.
Report text is untrusted data: the control never calls a model and never reads anything except the submitted report.
"""
import re

VERIFIED, UNSUPPORTED, CONFLICT, QUARANTINED = "verified", "unsupported", "conflict", "quarantined"
HOLD_STATUSES = (UNSUPPORTED, CONFLICT, QUARANTINED)
OBSERVATION, THRESHOLD, HISTORICAL, REFERENCE, INSTRUCTION, AMBIGUOUS = "observation", "threshold", "historical", "reference", "instruction", "ambiguous"

_ASSET = re.compile(r"\b([A-Z]{1,4}-\d{2,4}[A-Z]?)\b", re.IGNORECASE)
_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b|\b\d{4}-\d{2}-\d{2}\b")
_BOUNDARY = r"(?![A-Za-z0-9/²³])"
_NUMBER = r"(?<![\w.,])([-+]?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?)\s*"

# measurement type -> keyword regex, words that mean a *different* quantity, units: (canonical label, factor/convert, regex, implies the type by itself)
TYPES = {
    "vibration": {"keywords": r"vibrat\w*|shak\w*|velocity|\brms\b|tremor", "other": None, "canonical": "mm/s",
                  "units": [("mm/s", lambda v: v, r"mm\s*/\s*s(?:ec(?:onds?)?)?|mm\s+per\s+sec(?:ond)?s?|millimet(?:er|re)s?\s+(?:per|/)\s+second", True),
                            ("in/s", lambda v: v * 25.4, r"in\s*/\s*s(?:ec)?|ips|inch(?:es)?\s+(?:per|/)\s+sec(?:ond)?s?", False)]},
    "brake_pressure": {"keywords": r"brake\w*", "other": r"tyre|tire|\boil\b|fuel|hydraulic|discharge|suction|suspension|boost|cabin", "canonical": "psi",
                       "units": [("psi", lambda v: v, r"psi", False), ("bar", lambda v: v * 14.5037738, r"bar", False), ("kPa", lambda v: v * 0.145037738, r"kpa", False)]},
    "coolant_temperature": {"keywords": r"coolant|engine\s+temp", "other": r"ambient|\boil\b|exhaust|cabin|outside|intake|transmission", "canonical": "C",
                            "units": [("C", lambda v: v, r"(?:°\s*|deg(?:rees?)?\.?\s*)?C(?:elsius)?", False),
                                      ("F", lambda v: (v - 32.0) * 5.0 / 9.0, r"(?:°\s*|deg(?:rees?)?\.?\s*)?F(?:ahrenheit)?", False),
                                      ("K", lambda v: v - 273.15, r"K(?:elvin)?", False)]},
}
_PLAUSIBLE = {"vibration": (0.0, 250.0), "brake_pressure": (0.0, 400.0), "coolant_temperature": (-40.0, 220.0)}

def parse_number(raw: str, locale: str | None = None) -> dict:
    """Explicit numeric-notation policy. Returns {value, alts, notation, ambiguous, reason}; the original text is kept by the caller.

    Rules: digits only = integer; both separators = the last one is the decimal separator and the other must group by 3; a repeated separator must group by 3;
    a single separator followed by other than 3 digits (or after a leading 0, or after more than 3 digits) can only be decimal; a single separator followed by
    exactly 3 digits after 1-3 leading digits is AMBIGUOUS (1.100 = 1.1 or 1100) unless the source locale is stated ('en': '.' decimal, ',' grouping;
    'de': ',' decimal, '.' grouping). Ambiguous values keep every interpretation in `alts` and are never verified."""
    t = raw.strip()
    sign = 1.0
    if t[:1] in "+-":
        sign = -1.0 if t[0] == "-" else 1.0
        t = t[1:]
    m = re.fullmatch(r"(\d+(?:[.,]\d+)*)([eE][+-]?\d+)?", t)
    if not m:
        return {"value": None, "alts": [], "notation": "invalid", "ambiguous": True, "reason": "the number is not in a supported notation"}
    body, exp = m.group(1), m.group(2)
    mult = 10.0 ** int(exp[1:]) if exp else 1.0

    def res(value, notation, ambiguous=False, alts=None, reason=""):
        vals = [sign * v * mult for v in (alts if alts is not None else [value])]
        return {"value": sign * value * mult if value is not None else None, "alts": vals, "notation": notation + ("+scientific" if exp else ""), "ambiguous": ambiguous, "reason": reason}
    seps = [c for c in body if c in ".,"]
    if not seps:
        return res(float(body), "integer")
    if len(set(seps)) == 2:
        last = max(body.rfind("."), body.rfind(","))
        dec, grp = body[last], ("," if body[last] == "." else ".")
        groups = body[:last].split(grp)
        if grp in body[last + 1:] or not (1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])):
            return {"value": None, "alts": [], "notation": "invalid", "ambiguous": True, "reason": "mixed separators that do not form a valid grouping"}
        return res(float("".join(groups) + "." + body[last + 1:]), "grouped_decimal_point" if dec == "." else "grouped_decimal_comma")
    sep = seps[0]
    parts = body.split(sep)
    if len(seps) > 1:
        if 1 <= len(parts[0]) <= 3 and all(len(g) == 3 for g in parts[1:]):
            return res(float("".join(parts)), "grouped_integer")
        return {"value": None, "alts": [], "notation": "invalid", "ambiguous": True, "reason": "repeated separators that do not form a valid grouping"}
    lead, tail = parts
    if len(tail) != 3 or lead == "0" or len(lead) > 3:
        return res(float(lead + "." + tail), "decimal_point" if sep == "." else "decimal_comma_inferred")
    dec_v, grp_v = float(lead + "." + tail), float(lead + tail)
    if locale == "en":
        return res(dec_v if sep == "." else grp_v, "locale_en_decimal_point" if sep == "." else "locale_en_grouping")
    if locale == "de":
        return res(dec_v if sep == "," else grp_v, "locale_de_decimal_comma" if sep == "," else "locale_de_grouping")
    return res(dec_v, "ambiguous_three_digit_group", True, alts=[dec_v, grp_v],
               reason=f"'{raw}' is {dec_v:g} under decimal notation and {grp_v:g} under digit grouping; no source locale was stated, so it is not interpreted without a human")

_NAME_TO_TYPE = (("vibration", "vibration"), ("brake_pressure", "brake_pressure"), ("coolant_temp", "coolant_temperature"))
_ALL_KEYWORDS = {t: re.compile(spec["keywords"], re.IGNORECASE) for t, spec in TYPES.items()}

_CLAUSE_SEP = re.compile(r"\s*(?:,(?!\d)|\||\s+and\s+|\s+while\s+|\s+but\s+|\s+however\b)\s*", re.IGNORECASE)
_THRESHOLD = re.compile(r"threshold|limit|(?:alarm|alert)\s+(?:level|point|setting|value|is|at)|alarm\s+(?:threshold|limit)|set\s*point|setpoint|\btrip\b|allowable|\bmax(?:imum)?\b|\bmin(?:imum)?\b|must\s+not\s+exceed|should\s+(?:be|not)|"
                        r"exceed|\babove\b|\bbelow\b|\bup\s+to\b|at\s+least|at\s+most|calibrat", re.IGNORECASE)
_REFERENCE = re.compile(r"manual|specification|datasheet|data\s+sheet|typical|normal\s+range|design|expected|rated|nominal|target|class\s+limit", re.IGNORECASE)
_HISTORICAL = re.compile(r"previous|prior|formerly|last\s+(?:week|month|year|quarter|time|inspection|service)|earlier|yesterday|\(\s*was\b|up\s+from|down\s+from|"
                         r"compared\s+(?:to|with)|baseline|used\s+to|\bin\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|ago\b", re.IGNORECASE)
_IMPERATIVE = re.compile(r"\b(?:record|report|set(?!\s*point)|treat|mark|enter|assume|state|write|use|log|classify|rate|make)\b[^0-9]{0,30}$", re.IGNORECASE)
# text addressed to the assistant/system or trying to change rules, approval or priority: taints every reading in the report
_STRONG_INSTRUCTION = [re.compile(p, re.IGNORECASE) for p in (
    r"\b(?:assistant|llm|language\s+model|chatbot|system\s+prompt)\b", r"\bdear\s+(?:ai|model|bot)\b", r"\b(?:as|for|to)\s+the\s+model\b",
    r"\bsystem\s*(?:message)?\s*:", r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|rules?|instructions?|polic)",
    r"\boverride\s*:", r"\b(?:bypass|skip)\b[^.?!]{0,40}\b(?:approval|supervisor|review|rules?)\b", r"\bno\s+(?:supervisor\s+)?approvals?\s+(?:is\s+|are\s+)?(?:needed|required)\b",
    r"\b(?:submit|approve)\s+(?:the\s+)?(?:ticket|it|this)\b", r"\bescalate\s+(?:this\s+)?to\s+p[1-4]\b", r"\b(?:mark|set|treat|classify|rate|make)\b[^.?!]{0,30}\b(?:p[1-4]|critical|highest)\b",
    r"\b(?:note|message|instruction)s?\s+(?:to|for)\s+(?:the\s+)?(?:assistant|ai|model|system)\b")]


def _type_of(name: str) -> str | None:
    return next((t for prefix, t in _NAME_TO_TYPE if name.startswith(prefix)), None)


def _sentences(text: str) -> list[tuple[int, str]]:
    parts, start = [], 0
    for m in re.finditer(r"[.;!?]+(?=\s|$)|\n", text):
        parts.append((start, text[start:m.start()]))
        start = m.end()
    parts.append((start, text[start:]))
    return [(o, s) for o, s in parts if s.strip()]


def _clauses(sentence: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _CLAUSE_SEP.finditer(sentence):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(sentence)))
    return [(a, b) for a, b in spans if sentence[a:b].strip()]


def _mask(text: str, *patterns: re.Pattern) -> str:
    for p in patterns:
        text = p.sub(lambda m: "~" * len(m.group(0)), text)
    return text


# ---- V6: positive observation forms (a reading verifies only when it is in a recognised observation structure) and structural directive detection
_FILLER = (r"(?:[\s:=\-\u2013\u2014~]|\b(?:recorded\s+as|logged\s+as|reported\s+as|measured\s+as|came\s+out\s+at|is|was|now|currently|at|of|on|to|for|reads?|reading|measured|measures|"
           r"recorded|registered|came|out|shows?|showed|displayed|display|pressure|level|velocity|temperature|temp|circuit|line|gauge|value|approx\.?|about|around|only|ran|run|runs|"
           r"running|rose|climbed|dropped|fell|hit|reached|peaked|stood|sat|sits|stands|hot|the|a|an|air|check|test|result|results|output|rig|port|service)\b)*")
_FORM_BEFORE = re.compile(r"^" + _FILLER + r"$", re.IGNORECASE)
_FORM_AFTER = re.compile(r"^(?:[\s~]|\b(?:on|at|from|in|of|for|the|a|an|circuit|line|port|gauge|reading|test|rig|measured|recorded|service)\b)*$", re.IGNORECASE)
_RECORD_START = re.compile(r"^[\s~]*[:\-\u2013\u2014=|]*[\s~]*$")
_CUE = re.compile(r"analy[sz]er|sensor|meter|gauge|probe|reading|handheld|logged|measured|recorded|taken|telemetry|telematics|test|inspection|\breads?\b|shows?|displayed|read\b|\bgave\b|\bgives\b", re.IGNORECASE)
_CONTINUATION = re.compile(r"^[\s~]*$")
_HISTORICAL_AFTER = re.compile(r"\blast\s+(?:week|month|year|quarter|time|inspection|service|round|visit)\b|\bprevious|\bago\b|\bearlier\b|\bprior\b|\bformerly\b|\bat\s+the\s+(?:last|previous)\s+(?:inspection|service|round|visit|check)\b|\bin\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.IGNORECASE)
# directive structure: sentence addressed to a reader/system, role or bracket tags, vocatives, or an imperative that changes records, rules, approval or priority
_DIRECTIVE_VERB = re.compile(r"^[\s\"'\u201c\[(]*(?:please\s+)?(?:ignore|disregard|skip|bypass|override|forget|set|mark|treat|classify|rate|log|record(?!\s*[:\-])|report(?!\s*[:\-])|enter|escalate|submit|approve|assume|"
                             r"pretend|act|always|never|do\s+not|don't|from\s+now\s+on|make\s+sure|ensure|disable|turn\s+off)\b", re.IGNORECASE)
_DIRECTIVE_TAG = re.compile(r"^\s*[\[<(]\s*(?:system|assistant|ai|admin|instruction|prompt|user|note|developer)[^\]>)]*[\]>)]|^\s*(?:system|assistant|ai|admin|instruction)s?\s*[:\-]|"
                            r"\bdear\s+\w+|\bfrom\s+now\s+on\b|\b(?:for|to)\s+(?:the\s+)?(?:ai|assistant|model|llm|bot|system)\b", re.IGNORECASE)


def _directive(sentence: str) -> bool:
    """Structural test: is this sentence a directive (addressed to a reader or system, or an imperative altering records/rules/approval) rather than an observation?"""
    return bool(_DIRECTIVE_VERB.search(sentence) or _DIRECTIVE_TAG.search(sentence))


def _quoted(sentence: str, pos: int) -> bool:
    before = sentence[:pos]
    return (before.count('"') % 2 == 1) or (before.count("\u201c") > before.count("\u201d")) or (before.count("'") % 2 == 1 and before.rstrip().endswith(("'", ": '")) is False and False)


def _form(clause: str, n_start: int, n_end: int, kw_matches: list, implies: bool, carry_ok: bool) -> str | None:
    """Name of the recognised observation structure the number is in, or None when the context does not establish an observation."""
    before_kw = [k for k in kw_matches if k.end() <= n_start]
    if before_kw and _FORM_BEFORE.match(clause[before_kw[-1].end():n_start]):
        return "keyword-before-value"
    after_kw = [k for k in kw_matches if k.start() >= n_end]
    if after_kw and _FORM_AFTER.match(clause[n_end:after_kw[0].start()]):
        return "value-before-keyword"
    if carry_ok and _CONTINUATION.match(clause[:n_start]):
        return "continued-reading"
    if "~" in clause[:n_start] and _RECORD_START.match(clause[:n_start]):
        return "asset-record"
    if implies and _CUE.search(clause):
        return "cued-unit-reading"
    return None


def _context(window_before: str, window_after: str, notation_reason: str | None, report_tainted: bool, form: str | None = "keyword-before-value", rest: str = "", quoted: bool = False) -> tuple[str, str]:
    """Context class of one candidate number, from the words around it, with the reason."""
    if report_tainted:
        return INSTRUCTION, "the report contains text addressed to the assistant or trying to change rules, approval or priority; no reading in it is treated as an observation"
    if quoted:
        return INSTRUCTION, "the number is inside quoted text, which is not treated as the reporter's own observation"
    if _IMPERATIVE.search(window_before):
        return INSTRUCTION, "the number is preceded by an imperative or assignment ('record ... as', 'set ... to'), not by an observation"
    if notation_reason:
        return AMBIGUOUS, notation_reason
    if re.search(r"\d\s*[-\u2013]\s*$", window_before):
        return AMBIGUOUS, "the number is the end of a range or a hyphenated figure; a single current reading cannot be established"
    if _HISTORICAL.search(window_before) or _HISTORICAL_AFTER.search(rest):
        return HISTORICAL, "the figure is marked as a previous or historical value"
    if _THRESHOLD.search(window_before) or re.match(r"\s*(?:limit|threshold|alarm|alert|max|trip)", window_after, re.IGNORECASE):
        return THRESHOLD, "the figure is an alarm threshold, limit or setting, not an observed reading"
    if _REFERENCE.search(window_before):
        return REFERENCE, "the figure is a reference, specification or target value"
    if form is None:
        return AMBIGUOUS, "the number is not in a recognised observation structure (measurement keyword and value in order, asset-value record, or a cued reading); it is not treated as an observation"
    return OBSERVATION, "stated in the report as a current reading (" + form + ")"


def _candidates(report_text: str, asset_id: str, mtype: str | None, regex: str | None, unit: str, tainted: bool, report_assets: set[str], locale: str | None = None) -> list[dict]:
    """Every unit-bearing number of this measurement type in the report, classified and attributed."""
    out: list[dict] = []
    spec = TYPES.get(mtype) if mtype else None
    for s_off, sentence in _sentences(report_text):
        assets = [(m.start(), m.group(1).upper()) for m in _ASSET.finditer(sentence)]
        masked = _mask(sentence, _ASSET, _TIME)
        times = [(m.start(), m.group(0)) for m in _TIME.finditer(sentence)]
        found: list[tuple[int, int, int, int, str, object, str, bool, str | None, bool]] = []  # (clause_start, clause_end, num_start, end, number_text, factor_value, unit_label, converted)
        carry = False
        carry_form_ok = False
        for c_start, c_end in _clauses(masked):
            clause = masked[c_start:c_end]
            if spec:
                kw_matches = list(_ALL_KEYWORDS[mtype].finditer(clause))
                own_kw = bool(kw_matches)
                clause_form_ok = False
                foreign_kw = any(k.search(clause) for t, k in _ALL_KEYWORDS.items() if t != mtype)
                other = bool(spec["other"] and re.search(spec["other"], clause, re.IGNORECASE))
                for label, conv, unit_re, implies in spec["units"]:
                    for m in re.finditer(_NUMBER + "(?:" + unit_re + ")" + _BOUNDARY, clause, re.IGNORECASE):
                        if other or (foreign_kw and not own_kw):
                            continue
                        keywordless = not (own_kw or carry or implies)
                        raw = m.group(1)
                        parsed = parse_number(raw, locale)
                        form = None if keywordless else _form(clause, m.start(1), m.end(), kw_matches, implies, carry and carry_form_ok)
                        clause_form_ok = clause_form_ok or form is not None
                        conv_vals = [conv(v) for v in parsed["alts"]]
                        found.append((c_start, c_end, c_start + m.start(1), c_start + m.end(), raw, (parsed, conv_vals), label, label != spec["canonical"], form, keywordless))
                carry = (own_kw or (carry and not foreign_kw)) and not other
                carry_form_ok = clause_form_ok
            elif regex:
                for m in re.finditer(regex, clause, re.IGNORECASE):
                    raw = m.group(1)
                    parsed = parse_number(raw, locale)
                    found.append((c_start, c_end, c_start + m.start(1), c_start + m.end(), raw, (parsed, list(parsed["alts"])), unit, False, "profile-signal-pattern", False))
        found.sort(key=lambda f: f[2])
        prev_end = 0
        for c_start, c_end, n_start, n_end, raw, parsed_pair, label, converted, form, keywordless in found:
            lo = max(c_start, prev_end, n_start - 40)
            before, after = masked[lo:n_start], masked[n_end:min(c_end, n_end + 18)]
            prev_end = n_end
            parsed, conv_vals = parsed_pair
            norm = conv_vals[0] if conv_vals else 0.0
            ctx, why = _context(before, after, parsed["reason"] if parsed["ambiguous"] else None, tainted or _directive(sentence), form, re.split(r"[(\d]", masked[n_end:c_end])[0], _quoted(sentence, n_start))
            if assets:
                preceding = [a for a in assets if a[0] < n_start]
                owner = max(preceding, key=lambda a: a[0])[1] if preceding else min(assets, key=lambda a: abs(a[0] - n_start))[1]
            elif len(report_assets) <= 1:
                owner = asset_id.upper()
            else:
                owner = None
            if keywordless and not parsed["ambiguous"] and ctx in (OBSERVATION, AMBIGUOUS):
                ctx, why = AMBIGUOUS, "a unit-bearing number appears with no measurement keyword, so no measurement context is established"
            if ctx == OBSERVATION and mtype in _PLAUSIBLE and not (_PLAUSIBLE[mtype][0] <= norm <= _PLAUSIBLE[mtype][1]):
                ctx, why = AMBIGUOUS, "the converted value is outside the physically plausible range for this measurement"
            if owner is None and ctx == OBSERVATION:
                ctx, why = AMBIGUOUS, "the reading is in a sentence that names no asset while the report names several; it cannot be attributed to this asset"
            ts = None
            if times:
                ts = min(times, key=lambda t: abs(t[0] - n_start))[1]
            raw_clause = report_text[s_off + c_start:s_off + c_end]
            lead = len(raw_clause) - len(raw_clause.lstrip())
            span = raw_clause.strip()
            out.append({"asset": owner, "context": ctx, "why": why, "raw": raw, "normalized": round(norm, 6), "unit": label, "converted": converted,
                        "start": s_off + c_start + lead, "end": s_off + c_start + lead + len(span), "value_start": s_off + n_start, "value_end": s_off + n_end,
                        "span": span, "timestamp": ts, "alts": sorted({round(v, 6) for v in conv_vals}), "notation": parsed["notation"], "keywordless": keywordless})
    return out



def _structured_for(items: list[dict], mtype: str | None, asset_id: str, tenant_id: str | None = None) -> tuple[list[dict], list[dict]]:
    """Validate structured observation records for one measurement type. A record is trusted only when its asset matches the incident asset, the type and
    unit are supported, the value is finite and plausible, the optional timestamp is ISO 8601 and the free-text 'source' label is not directive.
    Origin and tenant come from the authenticated request, never from the payload (the API schema forbids a tenant field)."""
    import math
    from datetime import datetime
    good, bad = [], []
    spec = TYPES.get(mtype) if mtype else None
    if not spec:
        return good, bad
    lookup = {label.lower(): (label, conv) for label, conv, _, _ in spec["units"]}
    for idx, item in enumerate(items):
        if item.get("measurement_type") != mtype:
            continue
        ref = f"observations[{idx}]"

        def reject(why, idx=idx, ref=ref, item=item):
            bad.append({"index": idx, "ref": ref, "reason": "structured observation rejected: " + why, "value": item.get("value")})
        value = item.get("value")
        unit = str(item.get("unit", "")).strip().lower()
        if str(item.get("asset_id", "")).strip().upper() != asset_id.upper():
            reject(f"it is for asset {item.get('asset_id')!r}, not the incident asset")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            reject("the value is not a finite number")
        elif unit not in lookup:
            reject(f"unit {item.get('unit')!r} is not supported for {mtype}")
        elif item.get("source") and (_directive(str(item["source"])) or any(p.search(str(item["source"])) for p in _STRONG_INSTRUCTION)):
            reject("its source label is instruction-like text")
        elif item.get("simulation") and not __import__("app.ai.measurement_trust", fromlist=["x"]).verify_simulated_observation(tenant_id, item)[0]:
            reject(__import__("app.ai.measurement_trust", fromlist=["x"]).verify_simulated_observation(tenant_id, item)[1])
        else:
            label, conv = lookup[unit]
            norm = round(conv(float(value)), 6)
            ts = item.get("observed_at")
            if ts:
                try:
                    datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except ValueError:
                    reject("observed_at is not an ISO 8601 timestamp")
                    continue
            lo, hi = _PLAUSIBLE[mtype]
            if not lo <= norm <= hi:
                reject("the converted value is outside the physically plausible range")
                continue
            good.append({"normalized": norm, "raw": value, "unit": label, "converted": label != spec["canonical"], "ref": ref, "timestamp": ts, "source": item.get("source"),
                         "simulated": bool(item.get("simulation")), "sim_source": (item.get("simulation") or {}).get("source_id")})
    return good, bad


def _equal(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-6, 0.005 * max(abs(a), abs(b)))


def audit_measurements(report_text: str, asset_id: str, signals: list[tuple[str, str, str]],
                       proposed: dict[str, float | None], *, numeric_locale: str | None = None, structured: list[dict] | None = None,
                       provenance: dict | None = None, is_critical=None) -> tuple[dict[str, float | None], list[dict]]:
    """Return (canonical-unit values the priority rules may use, audit records).

    signals:  (name, regex, unit); the regex is used only for signal names that have no built-in measurement type
    proposed: name -> value the model (or the extraction client) proposed, or None
    """
    report_assets = {m.group(1).upper() for m in _ASSET.finditer(report_text)}
    tainted = any(p.search(s) or _directive(s) for _, s in _sentences(report_text) for p in _STRONG_INSTRUCTION[:1]) or any(p.search(s) for _, s in _sentences(report_text) for p in _STRONG_INSTRUCTION) or any(_directive(s) for _, s in _sentences(report_text))
    usable: dict[str, float | None] = {}
    records: list[dict] = []
    for name, regex, unit in signals:
        mtype = _type_of(name)
        canonical = TYPES[mtype]["canonical"] if mtype else unit
        cands = _candidates(report_text, asset_id, mtype, regex, canonical, tainted, report_assets, numeric_locale)
        model_value = proposed.get(name)
        own = [c for c in cands if c["context"] == OBSERVATION and c["asset"] == asset_id.upper()]
        foreign = [c for c in cands if c["context"] == OBSERVATION and c["asset"] != asset_id.upper()]
        held_instr = [c for c in cands if c["context"] == INSTRUCTION]
        model_f = float(model_value) if model_value is not None else None

        def _keep_keywordless(c, name=name, model_f=model_f):  # a keyword-less figure is held only when it anchors the model's proposal or would be safety-critical if true
            if not c["keywordless"]:
                return True
            return any((model_f is not None and _equal(v, model_f)) or (is_critical is not None and is_critical(name, v)) for v in c["alts"])
        held_ambig = [c for c in cands if c["context"] == AMBIGUOUS and _keep_keywordless(c)]
        base = {"name": name, "measurement_type": mtype or name, "asset_id": asset_id.upper(), "unit": canonical, "normalized_unit": canonical,
                "model_proposed_value": float(model_value) if model_value is not None else None, "source_document_id": None, "observation_timestamp": None,
                "evidence_span": None, "evidence_location": None, "converted": False, "normalized_value": None, "original_value": None, "original_unit": None}

        def record(status, context, reason, method, source, value=None, cand=None, candidate_values=(), base=base):
            rec = {**base, "value": value, "status": status, "verification_status": status, "context_type": context, "reason": reason,
                   "verification_reason": reason, "method": method, "source": source, "review_required": status != VERIFIED,
                   "candidate_values": sorted({round(v, 6) for v in candidate_values}), "numeric_notation": None, "numeric_locale": numeric_locale, "source_text": None,
                   "temporal_status": None, "provenance": None, "tenant_id": (provenance or {}).get("tenant_id"), "incident_id": None}
            if cand:
                rec.update({"numeric_notation": cand.get("notation"), "source_text": cand["raw"], "temporal_status": "current" if cand["context"] == OBSERVATION else cand["context"],
                            "normalized_value": cand["normalized"], "converted": cand["converted"], "original_value": cand["raw"], "original_unit": cand["unit"],
                            "evidence_span": cand["span"], "evidence_location": {"start": cand["start"], "end": cand["end"], "value_start": cand["value_start"], "value_end": cand["value_end"]}, "observation_timestamp": cand["timestamp"]})
            records.append(rec)

        s_good, s_bad = _structured_for(structured or [], mtype, asset_id, (provenance or {}).get("tenant_id"))
        for b in s_bad:
            records.append({**base, "value": None, "status": QUARANTINED, "verification_status": QUARANTINED, "context_type": AMBIGUOUS, "reason": b["reason"],
                            "verification_reason": b["reason"], "method": "structured_record_rejected", "source": "structured_record", "review_required": True,
                            "candidate_values": [], "numeric_notation": None, "numeric_locale": numeric_locale, "source_text": str(b["value"]), "temporal_status": None,
                            "provenance": {**(provenance or {}), "ref": b["ref"]}, "tenant_id": (provenance or {}).get("tenant_id"), "incident_id": None,
                            "evidence_span": b["ref"], "evidence_location": {"field": b["ref"]}})
        if s_good:
            vals: list[float] = []
            for g in s_good:
                if not any(_equal(g["normalized"], d) for d in vals):
                    vals.append(g["normalized"])
            first = s_good[0]
            rec = {**base, "value": None, "status": CONFLICT, "verification_status": CONFLICT, "context_type": OBSERVATION, "method": "structured_observation_record",
                   "source": "structured_record", "review_required": True, "candidate_values": sorted(vals), "numeric_notation": "structured_number", "numeric_locale": None,
                   "source_text": str(first["raw"]), "temporal_status": ("observed_at:" + str(first["timestamp"])) if first["timestamp"] else "submitted_with_report",
                   "provenance": {**(provenance or {}), "ref": first["ref"], "source": first["source"]}, "tenant_id": (provenance or {}).get("tenant_id"), "incident_id": None,
                   "evidence_span": first["ref"], "evidence_location": {"field": first["ref"]}, "observation_timestamp": first["timestamp"],
                   "original_value": str(first["raw"]), "original_unit": first["unit"], "converted": first["converted"],
                   "simulated": all(g["simulated"] for g in s_good), "simulation_source_id": first["sim_source"] if all(g["simulated"] for g in s_good) else None}
            if len(vals) > 1:
                usable[name] = None
                rec["reason"] = rec["verification_reason"] = "structured observation records state different current values: " + ", ".join(f"{v:g}" for v in sorted(vals))
            else:
                usable[name] = first["normalized"]
                note = ""
                if own and not any(_equal(c["normalized"], first["normalized"]) for c in own):
                    note = "; the free-text report states a different value, which was not used"
                if model_value is not None and not _equal(float(model_value), first["normalized"]):
                    note += f"; the model proposed {float(model_value):g}"
                rec.update({"value": first["normalized"], "normalized_value": first["normalized"], "status": VERIFIED, "verification_status": VERIFIED, "review_required": False,
                            "reason": "supplied as a structured observation record by the authenticated submitter for this asset" + note,
                            "verification_reason": "supplied as a structured observation record by the authenticated submitter for this asset" + note})
            records.append(rec)
            continue
        distinct: list[float] = []
        for c in own:
            if not any(_equal(c["normalized"], d) for d in distinct):
                distinct.append(c["normalized"])
        # a competing figure for this asset in an unrecognised context could be a contradicting current reading: it blocks verification instead of being ignored
        competing = [c for c in held_ambig if c["asset"] in (asset_id.upper(), None) and distinct and not any(_equal(c["normalized"], d) for d in distinct)]
        if competing and len(distinct) == 1:
            usable[name] = None
            record(QUARANTINED, AMBIGUOUS, "another figure for this measurement (" + f"{competing[0]['normalized']:g}" + ") is in a context that cannot be classified, so the reading cannot be verified: "
                   + competing[0]["why"], "unresolved_competing_figure", "report_text", cand=own[0], candidate_values=distinct + [c["normalized"] for c in competing])
            continue
        if len(distinct) > 1:
            usable[name] = None
            record(CONFLICT, OBSERVATION, "the report states different current values for this measurement: " + ", ".join(f"{v:g}" for v in sorted(distinct)),
                   "contradictory_current_readings", "report_text", cand=own[0], candidate_values=distinct)
            records[-1]["evidence_span"] = " | ".join(c["span"] for c in own)[:300]
        elif len(distinct) == 1:
            first = own[0]
            usable[name] = first["normalized"]
            note = ""
            if model_value is not None and not _equal(float(model_value), first["normalized"]):
                note = f"; the model proposed {float(model_value):g} and the report value was used"
            conv = f" (converted from {first['raw']} {first['unit']})" if first["converted"] else ""
            record(VERIFIED, OBSERVATION, "stated in the report as a current reading for this asset" + conv + note, "evidence_verified_observation", "report_text", value=first["normalized"], cand=first)
        elif held_instr:
            usable[name] = None
            record(QUARANTINED, INSTRUCTION, held_instr[0]["why"], "instruction_like_context", "report_text", cand=held_instr[0], candidate_values=[v for c in held_instr if c["asset"] in (asset_id.upper(), None) for v in c["alts"]])
        elif held_ambig:
            usable[name] = None
            record(QUARANTINED, AMBIGUOUS, held_ambig[0]["why"], "ambiguous_evidence", "report_text", cand=held_ambig[0], candidate_values=[v for c in held_ambig if c["asset"] in (asset_id.upper(), None) for v in c["alts"]])
        elif model_value is not None:
            usable[name] = None
            kinds = {c["context"] for c in cands}
            if foreign:
                why, ctx = "the only reading in the report belongs to a different asset", OBSERVATION
            elif THRESHOLD in kinds:
                why, ctx = "the only matching figure in the report is an alarm threshold, limit or setting, not an observed reading", THRESHOLD
            elif HISTORICAL in kinds:
                why, ctx = "the only matching figure in the report is a previous (historical) value, not a current reading", HISTORICAL
            elif REFERENCE in kinds:
                why, ctx = "the only matching figure in the report is a reference or specification value", REFERENCE
            elif re.search(r"(?<![\w.])" + re.escape(f"{float(model_value):g}") + r"(?![\w])", report_text):
                why, ctx = f"the value appears in the report without a compatible unit or measurement context ({canonical})", AMBIGUOUS
            else:
                why, ctx = "the value is not stated in the report", AMBIGUOUS
            record(UNSUPPORTED, ctx, why, "no_supporting_observation", "model_output",
                   candidate_values=[v for c in cands if c["context"] in (OBSERVATION, INSTRUCTION, AMBIGUOUS) and c["asset"] in (asset_id.upper(), None) and _keep_keywordless(c) for v in c["alts"]])
        else:
            usable[name] = None  # nothing reported, nothing proposed: no record
    return usable, records


def needs_review(records: list[dict]) -> bool:
    return any(r["status"] in HOLD_STATUSES for r in records)
