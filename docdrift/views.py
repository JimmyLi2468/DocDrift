"""Shape an answer and its evidence bundle for the operator page.

Pure presentation: every value here is copied from the answer, the bundle or the
record store; nothing is inferred that the pipeline did not already decide.
"""
from __future__ import annotations

from .corpus.historical import HISTORICAL
from .models import EvidenceBundle, OperatorAnswer

CONDITION_LABELS = {
    "C1_RELEVANT": "Relevant to the question and equipment",
    "C2_WITHIN_FRESHNESS_WINDOW": "Within the freshness window (from n-1)",
    "C3_FORMAL_RECORD": "Formal change record (governance policy)",
    "C4_DECISION_APPROVED": "Decision state confirmed APPROVED",
    "C5_APPROVER_IDENTIFIED": "Approver identity verified",
    "C6_AUTHORITY_IN_SCOPE": "Approver has authority for this scope",
    "C7_AUTHORITY_VALID_ON_DATE": "Authority valid on the decision date",
    "C8_NOT_ALREADY_INCORPORATED": "Not already incorporated",
    "C9_NOT_INVALIDATED": "Not invalidated by a later authorised decision",
}


def _person(store, pid):
    p = store.get_person(pid) if pid else None
    return {"id": p.person_id, "name": p.name, "role": p.role} if p else None


def _change(c, store) -> dict:
    comm = c.communication
    return {
        "comm_id": comm.comm_id, "change_ref": comm.change_ref, "channel": comm.channel.value,
        "date": str(comm.date), "subject": comm.subject, "body": comm.body,
        "author": _person(store, comm.author_person_id),
        "approver": _person(store, comm.approver_person_id),
        "decision_date": str(comm.decision_date) if comm.decision_date else None,
        "formal_record": comm.formal_approval_record_id, "scope": comm.scope_id,
        "affects": [{"doc_id": d, "sections": comm.affects_sections} for d in comm.affects_doc_ids],
        "decision_state": c.verdict.decision_state.value,
        "authority_state": c.verdict.authority_state.value,
        "classification": c.classification, "effective": c.effective,
        "topical_scope": c.scope, "relevance": c.relevance,
        "conditions": [{"id": k.condition, "label": CONDITION_LABELS.get(k.condition, k.condition),
                        "passed": k.passed, "detail": k.detail,
                        "skipped": k.detail.startswith("not evaluated")}
                       for k in c.verdict.conditions],
        "invalidated_by": c.verdict.invalidated_by, "thread": c.thread,
        "incorporation": ({"incorporated": c.incorporation.incorporated,
                           "reason": c.incorporation.reason,
                           "missing_terms": c.incorporation.missing_terms,
                           "matched_terms": c.incorporation.matched_terms}
                          if c.incorporation else None),
    }


def build_view(answer: OperatorAnswer, bundle: EvidenceBundle, store) -> dict:
    cited: dict[str, dict[int, list[str]]] = {}
    guidance = []
    for s in answer.guidance:
        cits = []
        for c in s.citations:
            ch = store.get_chunk(c.chunk_id)
            doc_id, version = (ch.doc_id, ch.version) if ch else (c.chunk_id, "")
            cited.setdefault(doc_id, {}).setdefault(c.page, []).append(c.quote)
            cits.append({"chunk_id": c.chunk_id, "label": c.label, "doc_id": doc_id,
                         "version": version, "page": c.page, "quote": c.quote,
                         "provenance": c.provenance.value})
        guidance.append({"text": s.text, "citations": cits})

    change_docs = {d: comm.communication.affects_sections
                   for comm in bundle.candidate_changes
                   for d in comm.communication.affects_doc_ids}
    documents = []
    for r in bundle.versions:
        hist = HISTORICAL.get(r.doc_id)
        documents.append({
            "doc_id": r.doc_id, "title": r.title, "version": r.current.version,
            "effective": str(r.current.effective_date), "doc_type": r.current.doc_type,
            "provenance": r.current.provenance.value,
            "abb_document_id": r.current.abb_document_id, "source_url": r.current.source_url,
            "previous_version": r.previous.version if r.previous else None,
            "previous_effective": str(r.previous.effective_date) if r.previous else None,
            "previous_is_synthetic": bool(r.previous and not r.previous.is_abb_publication),
            "compare_pages": [e.page for e in hist.pages] if hist else [],
            "freshness_search_from": str(r.freshness_search_from),
            "cited_pages": {str(p): q for p, q in cited.get(r.doc_id, {}).items()},
            "change_pages": [int(s) for s in change_docs.get(r.doc_id, []) if str(s).isdigit()],
            "role": ("cited" if r.doc_id in cited else
                     "targeted_by_change" if r.doc_id in change_docs else "searched"),
        })
    order = {"cited": 0, "targeted_by_change": 1, "searched": 2}
    documents.sort(key=lambda d: (order[d["role"]], d["doc_id"]))

    changes = [_change(c, store) for c in bundle.candidate_changes]
    eq = bundle.equipment.equipment
    return {
        "question": answer.question, "answered": answer.answered, "mode": answer.mode.value,
        "status": answer.status.value,
        "equipment": ({"asset_tag": eq.asset_tag, "name": eq.name, "model": eq.model,
                       "type_code": eq.type_code, "category": eq.category,
                       "site": eq.site, "line": eq.line} if eq else None),
        "equipment_summary": answer.equipment_summary,
        "equipment_confidence": answer.equipment_confidence,
        "equipment_evidence": bundle.equipment.evidence,
        "clarification_needed": answer.clarification_needed,
        "guidance": guidance, "documents": documents,
        "pending_change": answer.pending_change, "approval_evidence": answer.approval_evidence,
        "other_open_changes": answer.other_open_changes, "escalation": answer.escalation,
        "changes": changes,
        "has_unincorporated_approved_change": any(c["effective"] and c["topical_scope"] == "answer_relevant"
                                                  for c in changes),
        "gates": [g.model_dump() for g in answer.gates], "disclaimer": answer.disclaimer,
    }
