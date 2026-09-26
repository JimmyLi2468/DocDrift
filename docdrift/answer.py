"""Grounded answer assembly.

Guidance is selected from retrieved chunks, never generated. Each step quotes a span
of its source verbatim so the citation validator can prove it exists, and every
citation carries the provenance of its source document.
"""
from __future__ import annotations

import re

from .drift import effective_changes
from .embeddings import tokenize
from .models import (ChangeDisclosure, Citation, DocumentationStatus, EvidenceBundle,
                     GuidanceStep, OperatorAnswer)

_ITEM_SPLIT = re.compile(r"(?m)^(?=\s*\d+\.\s)")
_SENT_SPLIT = re.compile(r"(?<=\.)\s+(?=[A-Z0-9])")
_ENUM = re.compile(r"^\s*\d+\.\s+")

STOP = set("the a an of to in for and or is are be on at with from that this it if as by".split())


def _window(text: str, size: int = 320) -> list[str]:
    """Break a run-on span (selection tables, specification blocks) at word
    boundaries so it can still be quoted verbatim."""
    words, out, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > size:
            out.append(cur.strip())
            cur = ""
        cur += w + " "
    if cur.strip():
        out.append(cur.strip())
    return [p for p in out if len(p) >= 25]


def _units(text: str) -> list[str]:
    """Split a chunk into citable units: one per numbered step, otherwise one per
    sentence with line wrapping removed, so a quote is never a dangling fragment.
    Spans with no sentence structure are windowed rather than discarded."""
    out: list[str] = []
    for part in _ITEM_SPLIT.split(text):
        flat = " ".join(part.split())
        if not flat:
            continue
        pieces = [flat] if re.match(r"^\d+\.\s", flat) else _SENT_SPLIT.split(flat)
        for p in pieces:
            if len(p) < 25:
                continue
            out += [p] if len(p) <= 400 else _window(p)
    return out


def _fold(text: str) -> set[str]:
    """Token set with hyphenated compounds split and plurals folded, so that
    "transformer-rated starters" in a question reaches "transformer" and "starter"
    in the source text."""
    out: set[str] = set()
    for raw in tokenize(text):
        for t in raw.replace(".", "-").split("-"):
            if not t:
                continue
            out.add(t)
            if len(t) > 3 and t.endswith("es"):
                out.add(t[:-2])
            elif len(t) > 3 and t.endswith("s"):
                out.add(t[:-1])
    return out


def _keywords(question: str, fault_codes: list[str]) -> set[str]:
    return {t for t in _fold(question) if t not in STOP and len(t) > 2} | set(fault_codes)


def _readable(unit: str) -> bool:
    """Operator steps must read as sentences. A run of table cells ("IN1 IN2 Fault
    5091 ... Event B5A0 ...") is citable evidence but not an instruction."""
    if len(unit) > 320:
        return False
    toks = unit.split()
    words = sum(1 for t in toks if re.fullmatch(r"[a-z][a-z,;:.()'-]{2,}", t))
    return len(toks) <= 6 or words / len(toks) >= 0.5


_FAULT_ROW = re.compile(r"^(?:\d{3,4}\s)?[0-9A-F]{4}\s+[A-Z][a-z]")


def _span(unit: str, anchors: list[str], width: int = 220) -> str:
    """A verbatim span of table text around the first matched phrase or term,
    cut at word boundaries, so a specification can be quoted without the whole row."""
    low = unit.lower()
    at = min((low.find(a) for a in anchors if a in low), default=0)
    start = max(0, unit.rfind(" ", 0, max(0, at - 40)) + 1)
    end = unit.find(" ", min(len(unit), start + width))
    return unit[start: end if end > 0 else len(unit)].strip()


def compose_guidance(bundle: EvidenceBundle, llm, max_steps: int = 5) -> list[GuidanceStep]:
    """Select source text that actually answers the question.

    Prose sentences are quoted whole. Table text - where specifications live - is
    quoted as a verbatim window around the matched phrase, and only when it matches a
    phrase of the question or most of its terms. Nothing is ever promoted on chunk
    score alone; if nothing clears the floor the answer stays empty and gate G3
    withholds it rather than padding it.
    """
    from .drift import GENERIC_TOPIC_TERMS

    faults = bundle.equipment.fault_codes
    kw = (_keywords(bundle.question, faults) - GENERIC_TOPIC_TERMS
          - {"fault", "faults", "trip", "trips", "tripping", "than", "book", "say", "says"}) | set(faults)
    # Overlap is counted per question word, not per folded variant, so "terminals"
    # and its singular do not count twice in the denominator.
    q_words = [w for w in dict.fromkeys(re.findall(r"[a-z0-9]+", bundle.question.lower()))
               if _fold(w) & kw]

    def overlap_of(unit: str) -> float:
        folds = _fold(unit)
        return sum(1 for w in q_words if _fold(w) & folds) / max(len(q_words), 1)
    ordered = [w for w in re.findall(r"[a-z0-9]+", bundle.question.lower())
               if w not in STOP and len(w) > 1]
    bigrams = [f"{a} {b}" for a, b in zip(ordered, ordered[1:])]

    # Already reranked. The top page carries the answer; a runner-up joins only when it
    # scored almost as well, so a weaker page cannot pad the steps.
    ranked = bundle.guidance_chunks
    best = ranked[0].score if ranked else 0.0
    pool = [rc for rc in ranked[:2] if rc.score >= 0.95 * best]
    if faults:
        # The page that defines the fault (its row in the fault table) answers a fault
        # question; pages that only mention the code are not used for steps.
        from .rerank import fault_definition
        defining = [rc for rc in ranked if any(fault_definition(rc.chunk.text, f) for f in faults)][:1]
        anchored = [rc for rc in ranked if any(f in rc.chunk.text for f in faults)][:2]
        pool = defining or anchored or pool
    top = max((rc.score for rc in pool), default=1.0) or 1.0

    scored: list[tuple[float, int, int, str, object]] = []
    for rank, rc in enumerate(pool):
        units = _units(rc.chunk.text)
        # The sentences right after the fault's own row are its explanation ("Check
        # safety circuit connections."), up to the next fault row.
        fault_at = next((i for i, u in enumerate(units) if any(f in u for f in faults)), None)
        fault_end = None
        if fault_at is not None:
            other_code = re.compile(r"(?<![0-9A-Za-z.])(?!(?:" + "|".join(map(re.escape, faults))
                                    + r")\b)[0-9A-F]{4}\s+[A-Z][a-z]")
            fault_end = next((k for k in range(fault_at + 1, len(units))
                              if _FAULT_ROW.match(units[k]) or other_code.search(units[k])),
                             len(units))
        for pos, unit in enumerate(units):
            low = " ".join(re.findall(r"[a-z0-9]+", unit.lower()))
            phrases = [b for b in bigrams if b in low]
            overlap = overlap_of(unit)
            follows_fault = fault_at is not None and fault_at < pos < min(fault_end, fault_at + 3)
            if not _readable(unit):
                if faults or (not phrases and overlap < 0.5):
                    continue
                unit = _span(unit, phrases or sorted(kw & _fold(unit), key=len, reverse=True))
            if overlap == 0.0 and not follows_fault and not (fault_at == pos):
                continue
            if faults and fault_at is not None and not (fault_at <= pos < fault_end) and overlap < 0.5:
                continue                         # another fault's row on the same page
            score = (overlap + 0.5 * len(phrases) + 0.6 * rc.score / top
                     + (0.8 if any(f in unit for f in faults) else 0.0)
                     + (0.5 if follows_fault else 0.0)
                     + (0.15 if _ENUM.match(unit) else 0.0))
            scored.append((score, rank, pos, unit, rc.chunk))
    scored.sort(key=lambda t: -t[0])
    seen, picked = set(), []
    for item in scored:
        if item[3] in seen:
            continue
        seen.add(item[3]); picked.append(item)
        if len(picked) == max_steps:
            break
    picked.sort(key=lambda t: (t[1], t[2]))

    return [GuidanceStep(
        text=llm.rephrase(_ENUM.sub("", unit)),
        citations=[Citation(chunk_id=chunk.chunk_id, label=chunk.citation_label,
                            quote=unit, page=chunk.page, provenance=chunk.provenance)])
        for _, _, _, unit, chunk in picked]


#: Order in which failed conditions explain a refusal: the substantive reason first
#: (no authority, not approved, invalidated) and the procedural one (no formal record,
#: not relevant) after it.
_REASON_ORDER = ["C6_AUTHORITY_IN_SCOPE", "C7_AUTHORITY_VALID_ON_DATE", "C4_DECISION_APPROVED",
                 "C9_NOT_INVALIDATED", "C5_APPROVER_IDENTIFIED", "C8_NOT_ALREADY_INCORPORATED",
                 "C3_FORMAL_RECORD", "C2_WITHIN_FRESHNESS_WINDOW", "C1_RELEVANT"]


def _mentions(text: str, fault_codes: list[str], subject: str) -> bool:
    if any(f in text for f in fault_codes):
        return True
    words = {w.lower() for w in re.findall(r"[A-Za-z]{5,}", subject)}
    return sum(1 for w in words if w in text.lower()) >= 2


def excerpt(text: str, fault_codes: list[str], subject: str, width: int = 240) -> str:
    """The passage of a page that the change is about, not the top of the page."""
    flat = " ".join(text.split())
    at = next((flat.find(f) for f in fault_codes if f in flat), -1)
    if at < 0:
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z]{3,}", subject)]
        hits = [flat.lower().find(w.lower()) for w in words if w.lower() in flat.lower()]
        at = min(hits) if hits else 0
    start = max(0, at - 20)
    return ("..." if start else "") + flat[start:start + width] + "..."


def _disclose(candidate) -> ChangeDisclosure:
    comm = candidate.communication
    failed = sorted((c for c in candidate.verdict.conditions if not c.passed),
                    key=lambda c: (c.detail.startswith("not evaluated"),
                                   _REASON_ORDER.index(c.condition)
                                   if c.condition in _REASON_ORDER else 99))
    detail = [f"{c.condition}: {c.detail}" for c in failed]
    return ChangeDisclosure(
        comm_id=comm.comm_id, change_ref=comm.change_ref, channel=comm.channel,
        date=comm.date, subject=comm.subject, classification=candidate.classification,
        decision_state=candidate.verdict.decision_state,
        authority_state=candidate.verdict.authority_state,
        failed_conditions=candidate.verdict.failed, detail=detail)


def build_answer(bundle: EvidenceBundle, store, llm) -> OperatorAnswer:
    eq = bundle.equipment.equipment
    if eq is None:
        return OperatorAnswer(
            question=bundle.question, answered=False, mode=bundle.mode,
            equipment_summary="not identified",
            equipment_confidence=bundle.equipment.confidence,
            status=DocumentationStatus.INSUFFICIENT_EVIDENCE,
            clarification_needed=("I could not match the equipment in your question to the "
                                  "asset registry. Please give the asset tag (for example M4) "
                                  "or the type code from the rating plate."))

    steps = compose_guidance(bundle, llm)
    # List the documents the answer rests on - cited, or targeted by a change that was
    # examined - and summarise the rest of the asset's library rather than listing it.
    cited_docs = {c.chunk_id and store.get_chunk(c.chunk_id).doc_id
                  for s in steps for c in s.citations if store.get_chunk(c.chunk_id)}
    change_docs = {d for c in bundle.candidate_changes for d in c.communication.affects_doc_ids}
    shown = [r for r in bundle.versions if r.doc_id in cited_docs | change_docs]
    docs = [f"{r.doc_id} rev {r.current.version} - {r.title} (effective {r.current.effective_date}"
            + (", ABB publication)" if r.current.is_abb_publication else ", synthetic stand-in)")
            + (", previous revision " + r.previous.version + " is a synthetic reconstruction"
               if r.previous is not None and not r.previous.is_abb_publication else "")
            for r in shown]
    if len(bundle.versions) > len(shown):
        docs.append(f"{len(bundle.versions) - len(shown)} further ABB publications in the asset "
                    f"register for {eq.asset_tag} were searched and not cited")

    other_open = [
        f"{c.communication.comm_id} ({c.communication.date}) affects "
        f"{', '.join(c.communication.affects_doc_ids) or 'this asset'} and is approved but not "
        f"yet reflected in the current revision. It does not bear on the question asked."
        for c in effective_changes(bundle.candidate_changes, scope="asset_open_change")
    ]

    pending, approval_evidence, escalation = None, [], None
    drifting = effective_changes(bundle.candidate_changes)
    if drifting:
        c = drifting[0]
        comm, verdict = c.communication, c.verdict
        approver = store.get_person(comm.approver_person_id) if comm.approver_person_id else None
        pending = f"{comm.comm_id}: {comm.subject}. {comm.body}"
        approval_evidence = [
            f"Channel: {comm.channel.value}"
            + (f", formal record {comm.formal_approval_record_id}"
               if comm.formal_approval_record_id else ", no formal record"),
            f"Decision: {verdict.decision_state.value} on {comm.decision_date or comm.date}",
            f"Approver: {approver.name} ({approver.role})" if approver else "Approver: unresolved",
            f"Authority: {verdict.authority_state.value} for scope '{comm.scope_id}'",
            f"Governance mode: {verdict.mode.value}; all nine conditions satisfied",
        ]
        if c.incorporation:
            approval_evidence.append(f"Incorporation check: {c.incorporation.reason}")
        for cid in (c.incorporation.compared_against[:2] if c.incorporation else []):
            src = store.get_chunk(cid)
            if src and _mentions(src.text, comm.fault_codes, comm.subject):
                approval_evidence.append(
                    f"Text still in force [{src.citation_label}]: "
                    + excerpt(src.text, comm.fault_codes, comm.subject))
        res = next((r for r in bundle.versions if r.doc_id in comm.affects_doc_ids), None)
        owner = store.get_person(res.current.owner_person_id) if res and res.current.owner_person_id else None
        who = f"{owner.name} ({owner.role})" if owner else "the responsible document owner"
        escalation = (f"Confirm with {who} whether {comm.comm_id} applies to {eq.asset_tag} before "
                      f"acting on it. The controlled document has not been updated; DocDrift "
                      f"cannot authorise the change.")

    return OperatorAnswer(
        question=bundle.question, answered=True, mode=bundle.mode,
        equipment_summary=(f"{eq.asset_tag} - {eq.name}, {eq.model} ({eq.category}), "
                           f"{eq.site}/{eq.line}"),
        equipment_confidence=bundle.equipment.confidence,
        guidance=steps, applicable_documents=docs, status=bundle.status,
        pending_change=pending, approval_evidence=approval_evidence,
        other_open_changes=other_open,
        evidence_considered=[_disclose(c) for c in bundle.candidate_changes],
        escalation=escalation)
