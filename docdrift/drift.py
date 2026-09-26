"""Temporal change search and the governance test.

This is the part a conventional RAG assistant does not do: find what was said after
the document was published, work out whether any of it is an approved change the
document does not yet reflect, and refuse everything that cannot prove itself.
"""
from __future__ import annotations

from datetime import date

from .config import Thresholds
from .embeddings import cosine, tokenize
from .governance import (FLEXIBLE_APPROVAL_CHANNELS, FORMAL_RECORD_CHANNELS,
                         INVALIDATING_STATES, AuthorityMatrix, AuthorityState,
                         ConditionResult, DecisionState, GovernanceMode,
                         GovernanceVerdict)
from .models import (CandidateChange, Communication, Equipment, IncorporationCheck,
                     VersionResolution)

STOP = set("the a an of to in for and or is are be on at with from that this it if as by after "
           "what causes check drive unit my our we i you should do does".split())


def _norm(s: str) -> str:
    return " ".join(tokenize(s))


# ------------------------------------------------------------------ C1 relevance

_SUFFIXES = ("ations", "ation", "ings", "ing", "ions", "ion", "ed", "es", "s")


def _stems(text: str) -> set[str]:
    """Crude suffix folding so "inspected" in the question meets "inspection" in a
    change notice, and "terminals" meets "terminal". Good enough for topical scoping;
    nothing downstream depends on it being linguistically correct."""
    out = set()
    for raw in tokenize(text):
        for t in raw.replace(".", "-").split("-"):
            if not t:
                continue
            out.add(t)
            for suf in _SUFFIXES:
                if len(t) - len(suf) >= 4 and t.endswith(suf):
                    out.add(t[: -len(suf)])
                    break
    return out


#: Words that name the kind of equipment or are generic to any maintenance question.
#: They establish which asset is meant - that is entity resolution's job - and say
#: nothing about which topic the question is on, so they never count toward C1.
GENERIC_TOPIC_TERMS = _stems(
    "drive drives softstarter softstarters contactor contactors breaker breakers starter "
    "starters relay relays module modules device devices unit units equipment machine motor "
    "operating operation operate use used need needs required require should must check "
    "what how often when which does still documentation manual say says line feeder plant")


def asset_terms(equipment: Equipment | None) -> set[str]:
    if equipment is None:
        return set()
    # Identifiers only. The asset's descriptive name ("transformer primary protection
    # breaker") is deliberately excluded: its words are often exactly the topic.
    # The category label ("motor_protection") is left out for the same reason.
    return _stems(" ".join(filter(None, [equipment.asset_tag, equipment.model,
                                         equipment.family, equipment.type_code,
                                         equipment.line])))


def score_topicality(question: str, fault_codes: list[str], comm: Communication,
                     embedder, th: Thresholds,
                     docs_in_use: set[str] | None = None,
                     equipment: Equipment | None = None) -> tuple[str, float]:
    """Does this change bear on the question asked, or merely on the same asset?

    Answer-relevant changes can move the documentation status. Everything else that
    affects the asset is still disclosed, as an advisory, so a question about one
    subject is not answered with a banner about another.

    Three signals, in decreasing strength: the fault code the operator quoted, the
    change touching a document the answer is actually built from, and plain lexical
    or semantic closeness.
    """
    ignore = GENERIC_TOPIC_TERMS | asset_terms(equipment)
    q_terms = {t for t in _stems(question) if t not in STOP and len(t) > 2 and t not in ignore}
    c_terms = _stems(comm.subject + " " + comm.body)
    shared = q_terms & c_terms
    lexical = len(shared) / max(len(q_terms), 1)

    if fault_codes and comm.fault_codes:
        if set(fault_codes) & set(comm.fault_codes):
            return "answer_relevant", 1.0
        return "asset_open_change", round(lexical, 3)

    # One shared word is not a topic. "Safe Torque Off" and "terminal tightening
    # torque" share "torque" and have nothing to do with each other, so the test is
    # two independent content terms, not a ratio that a short question inflates.
    strong = len(shared) >= th.topical_min_shared_terms
    touches_cited_document = bool(docs_in_use and set(comm.affects_doc_ids) & docs_in_use)
    vecs = embedder.encode([question, comm.subject + " " + comm.body])
    sim = cosine(vecs[0], vecs[1])

    relevant = strong and (touches_cited_document
                           or lexical >= th.topical_relevance_min
                           or sim >= th.topical_similarity_min)
    return ("answer_relevant" if relevant else "asset_open_change"), round(max(lexical, sim), 3)


# ------------------------------------------------------------------ C8 incorporation

def check_incorporation(comm: Communication, resolution: VersionResolution, store,
                        embedder, th: Thresholds) -> IncorporationCheck:
    chunks = store.chunks_for(resolution.doc_id, resolution.current.version)
    if comm.affects_sections:
        targeted = [c for c in chunks if c.section in comm.affects_sections]
        chunks = targeted or chunks
    if not chunks:
        return IncorporationCheck(incorporated=False, term_coverage=0.0, similarity=0.0,
                                  missing_terms=comm.normative_terms,
                                  reason="no indexed text for the affected section")

    haystack = _norm(" ".join(c.text for c in chunks))
    matched = [t for t in comm.normative_terms if _norm(t) in haystack]
    missing = [t for t in comm.normative_terms if t not in matched]
    coverage = len(matched) / len(comm.normative_terms) if comm.normative_terms else 0.0

    vecs = embedder.encode([comm.body] + [c.text for c in chunks])
    sim = max(cosine(vecs[0], v) for v in vecs[1:])

    approved_on = comm.decision_date or comm.date
    published_after = resolution.current.effective_date >= approved_on
    incorporated = coverage >= th.incorporation_term_coverage and published_after

    if incorporated:
        reason = (f"current revision {resolution.current.version} took effect "
                  f"{resolution.current.effective_date}, after the {approved_on} approval, and "
                  f"carries {len(matched)}/{len(comm.normative_terms)} of the required terms")
    elif not published_after:
        reason = (f"current revision {resolution.current.version} took effect "
                  f"{resolution.current.effective_date}, before the change was approved on "
                  f"{approved_on}")
    else:
        reason = f"current revision {resolution.current.version} is missing: {', '.join(missing)}"

    return IncorporationCheck(incorporated=incorporated, term_coverage=round(coverage, 3),
                              similarity=round(sim, 3), matched_terms=matched,
                              missing_terms=missing,
                              compared_against=[c.chunk_id for c in chunks], reason=reason)


# ------------------------------------------------------------------ C9 invalidation

def find_invalidations(comm: Communication, thread: list[Communication], store,
                       authority: AuthorityMatrix) -> list[tuple[str, str]]:
    """Later decisions that retire this approval.

    Authority applies to reversals exactly as it applies to approvals: a technician
    declaring a change cancelled does not cancel it. Each candidate reversal is
    therefore re-checked against the authority matrix before it is allowed to count.
    """
    approved_on = comm.decision_date or comm.date
    out: list[tuple[str, str]] = []
    for later in thread:
        if later.comm_id == comm.comm_id or later.date < approved_on:
            continue
        if later.decision_state not in INVALIDATING_STATES:
            continue
        person = store.get_person(later.approver_person_id or later.author_person_id)
        if person is None:
            out.append((later.comm_id, "ignored: author not resolvable in personnel records"))
            continue
        state, detail = authority.evaluate(person.role, later.scope_id or comm.scope_id,
                                           later.decision_date or later.date)
        if state is AuthorityState.VERIFIED:
            out.append((later.comm_id,
                        f"{later.decision_state.value} by {person.name} ({person.role}) "
                        f"on {later.decision_date or later.date}"))
        else:
            out.append((later.comm_id,
                        f"ignored: {later.decision_state.value} claimed by {person.name} "
                        f"({person.role}) but {detail}"))
    return out


# ------------------------------------------------------------------ the conjunctive test

def evaluate_change(comm: Communication, *, store, authority: AuthorityMatrix,
                    resolution: VersionResolution | None, thread: list[Communication],
                    scope: str, relevance: float, mode: GovernanceMode,
                    embedder, th: Thresholds
                    ) -> tuple[GovernanceVerdict, IncorporationCheck | None]:
    conditions: list[ConditionResult] = []

    def add(name: str, passed: bool, detail: str) -> bool:
        conditions.append(ConditionResult(condition=name, passed=passed, detail=detail))
        return passed

    add("C1_RELEVANT", scope == "answer_relevant",
        f"topical relevance {relevance:.2f}; {'bears on the question' if scope == 'answer_relevant' else 'affects the asset but not the question asked'}")

    within = resolution is None or comm.date >= resolution.freshness_search_from
    add("C2_WITHIN_FRESHNESS_WINDOW", within,
        (f"dated {comm.date}; window opens {resolution.freshness_search_from}"
         if resolution else f"dated {comm.date}; no document window to test against"))

    if mode is GovernanceMode.STRICT:
        formal_ok = (comm.channel in FORMAL_RECORD_CHANNELS
                     and bool(comm.formal_approval_record_id))
        formal_detail = (f"strict mode: formal change record {comm.formal_approval_record_id}"
                         if formal_ok else
                         f"strict mode: no formal change record ({comm.channel.value}, "
                         f"record={comm.formal_approval_record_id or 'none'})")
    else:
        formal_ok = comm.channel in FLEXIBLE_APPROVAL_CHANNELS
        formal_detail = (f"flexible mode: direct approval admissible on {comm.channel.value}"
                         if formal_ok else
                         f"flexible mode: {comm.channel.value} cannot carry a direct approval")
    add("C3_FORMAL_RECORD", formal_ok, formal_detail)

    add("C4_DECISION_APPROVED", comm.decision_state is DecisionState.APPROVED,
        f"decision state {comm.decision_state.value}")

    person = store.get_person(comm.approver_person_id) if comm.approver_person_id else None
    identified = person is not None
    add("C5_APPROVER_IDENTIFIED", identified,
        (f"{person.name} ({person.role}) resolved in personnel records" if person else
         "no approver named, or the named approver is not in personnel records"))

    if not identified:
        authority_state = (AuthorityState.NOT_CHECKED
                           if comm.decision_state in (DecisionState.DISCUSSION,
                                                      DecisionState.PROPOSED)
                           else AuthorityState.UNVERIFIED)
        add("C6_AUTHORITY_IN_SCOPE", False, "not evaluated: no identified approver")
        add("C7_AUTHORITY_VALID_ON_DATE", False, "not evaluated: no identified approver")
    else:
        authority_state, detail = authority.evaluate(person.role, comm.scope_id,
                                                     comm.decision_date or comm.date)
        add("C6_AUTHORITY_IN_SCOPE",
            authority_state not in (AuthorityState.OUT_OF_SCOPE, AuthorityState.NOT_APPLICABLE,
                                    AuthorityState.UNVERIFIED), detail)
        add("C7_AUTHORITY_VALID_ON_DATE", authority_state is not AuthorityState.EXPIRED, detail)

    incorporation: IncorporationCheck | None = None
    so_far = all(c.passed for c in conditions)
    if so_far and resolution is not None:
        incorporation = check_incorporation(comm, resolution, store, embedder, th)
        add("C8_NOT_ALREADY_INCORPORATED", not incorporation.incorporated, incorporation.reason)
    else:
        # Not evaluated. Recorded as satisfied so that `failed` lists only the
        # conditions that genuinely failed; the detail says plainly it was skipped.
        add("C8_NOT_ALREADY_INCORPORATED", True,
            "not evaluated: an earlier condition already failed" if not so_far
            else "not evaluated: no applicable document version to compare against")

    invalidations = find_invalidations(comm, thread, store, authority)
    effective_reversals = [cid for cid, why in invalidations if not why.startswith("ignored")]
    add("C9_NOT_INVALIDATED", not effective_reversals,
        "; ".join(f"{cid}: {why}" for cid, why in invalidations) or
        "no later decision retires this approval")

    verdict = GovernanceVerdict(
        comm_id=comm.comm_id, change_ref=comm.change_ref, mode=mode,
        decision_state=comm.decision_state, authority_state=authority_state,
        effective=all(c.passed for c in conditions), conditions=conditions,
        invalidated_by=effective_reversals)
    return verdict, incorporation


# ------------------------------------------------------------------ search

def find_candidate_changes(store, authority: AuthorityMatrix, embedder,
                           equipment: Equipment, resolutions: list[VersionResolution],
                           question: str, fault_codes: list[str], th: Thresholds,
                           mode: GovernanceMode,
                           docs_in_use: set[str] | None = None) -> list[CandidateChange]:
    if not resolutions:
        return []
    earliest = min(r.freshness_search_from for r in resolutions)
    by_doc = {r.doc_id: r for r in resolutions}

    everything = store.communications_since(date(1970, 1, 1))
    threads: dict[str, list[Communication]] = {}
    for c in everything:
        if c.change_ref:
            threads.setdefault(c.change_ref, []).append(c)

    out: list[CandidateChange] = []
    for comm in store.communications_since(earliest):
        # applicability: this asset's family/model, and a document this answer relies on
        if comm.equipment_families and equipment.family not in comm.equipment_families:
            continue
        if comm.equipment_models and equipment.model not in comm.equipment_models \
                and not comm.equipment_families:
            continue
        if comm.affects_doc_ids and not set(comm.affects_doc_ids) & set(by_doc):
            continue
        resolution = next((by_doc[d] for d in comm.affects_doc_ids if d in by_doc), None)

        # only decisions and proposals are worth governing; pure chatter is dropped here
        if comm.decision_state is DecisionState.DISCUSSION and not comm.change_ref:
            continue

        scope, relevance = score_topicality(question, fault_codes, comm, embedder, th,
                                            docs_in_use=docs_in_use, equipment=equipment)
        thread = threads.get(comm.change_ref, []) if comm.change_ref else []
        verdict, incorporation = evaluate_change(
            comm, store=store, authority=authority, resolution=resolution, thread=thread,
            scope=scope, relevance=relevance, mode=mode, embedder=embedder, th=th)

        out.append(CandidateChange(communication=comm, verdict=verdict, scope=scope,
                                   incorporation=incorporation, relevance=relevance,
                                   thread=[c.comm_id for c in thread]))

    out.sort(key=lambda c: (-int(c.effective), -int(c.scope == "answer_relevant"),
                            -c.relevance, c.communication.date))
    return out[: th.drift_top_k]


def effective_changes(changes: list[CandidateChange], scope: str | None = "answer_relevant"):
    """Changes that passed every condition and may therefore alter guidance."""
    return [c for c in changes if c.effective and (scope is None or c.scope == scope)]
