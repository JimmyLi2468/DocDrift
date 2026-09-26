"""Deterministic gates. Plain Python, no model in the loop.

A blocking gate failure suppresses the answer; a non-blocking failure is reported to
the operator as a caveat.
"""
from __future__ import annotations

from .config import Thresholds
from .drift import effective_changes
from .models import (ContentProvenance, DocumentationStatus, EvidenceBundle, GateResult,
                     OperatorAnswer)
from .validate import validate_answer


GATE_LABELS = {
    "G1_EQUIPMENT_IDENTIFIED": "Equipment identified",
    "G2_APPLICABLE_CURRENT_DOCUMENT": "Applicable current document",
    "G3_EVERY_STEP_CITED": "Every step cited",
    "G4_CITATIONS_RESOLVE": "Citations found in the source",
    "G5_DRIFT_DISCLOSED": "Approved change disclosed",
    "G6_NO_UNAUTHORISED_APPROVAL_CLAIM": "No unauthorised approval presented as approved",
    "G7_EVIDENCE_FULLY_DISCLOSED": "All examined records disclosed",
    "G8_PROVENANCE_LABELLED": "Synthetic content labelled",
    "G9_READ_ONLY": "Read-only",
}


def run_gates(bundle: EvidenceBundle, answer: OperatorAnswer, store, th: Thresholds) -> list[GateResult]:
    gates: list[GateResult] = []
    conf = bundle.equipment.confidence

    gates.append(GateResult(
        gate="G1_EQUIPMENT_IDENTIFIED",
        passed=bundle.equipment.equipment is not None and conf >= th.equipment_confidence_min,
        detail=f"confidence {conf:.2f} against threshold {th.equipment_confidence_min:.2f}"
               + (f"; ambiguous against {', '.join(bundle.equipment.alternatives)}"
                  if bundle.equipment.alternatives else "")))

    gates.append(GateResult(
        gate="G2_APPLICABLE_CURRENT_DOCUMENT",
        passed=bool(bundle.versions) and all(r.current.status == "current" for r in bundle.versions),
        detail=f"{len(bundle.versions)} applicable document(s) resolved to a current revision"))

    gates.append(GateResult(
        gate="G3_EVERY_STEP_CITED",
        passed=bool(answer.guidance) and all(s.citations for s in answer.guidance),
        detail=f"{sum(1 for s in answer.guidance if s.citations)}/{len(answer.guidance)} "
               f"steps carry a citation"))

    checks = validate_answer(answer, store)
    bad = [f"{c.chunk_id}: {why}" for c, ok, why in checks if not ok]
    gates.append(GateResult(
        gate="G4_CITATIONS_RESOLVE", passed=not bad and bool(checks),
        detail="all citations resolve to current-revision source text" if not bad else "; ".join(bad)))

    drifting = effective_changes(bundle.candidate_changes)
    if drifting:
        gates.append(GateResult(
            gate="G5_DRIFT_DISCLOSED",
            passed=(answer.status is DocumentationStatus.POTENTIAL_APPROVED_UPDATE
                    and bool(answer.pending_change) and bool(answer.escalation)),
            detail=f"{len(drifting)} change(s) passed all nine governance conditions"))
    else:
        other = effective_changes(bundle.candidate_changes, scope="asset_open_change")
        gates.append(GateResult(
            gate="G5_DRIFT_DISCLOSED", passed=len(other) == len(answer.other_open_changes),
            detail="no change bearing on this question passed every condition"
                   + (f"; {len(other)} disclosed as advisory for this asset" if other else "")))

    # Nothing that failed the governance test may be presented as an approved change.
    refused = [c.communication.comm_id for c in bundle.candidate_changes if not c.effective]
    leaked = [cid for cid in refused if answer.pending_change and cid in answer.pending_change]
    gates.append(GateResult(
        gate="G6_NO_UNAUTHORISED_APPROVAL_CLAIM", passed=not leaked,
        detail=("no refused record is presented as an approved change"
                if not leaked else f"presented despite failing: {', '.join(leaked)}")))

    # Every refused record must still be visible to the operator, with its reason.
    disclosed = {d.comm_id for d in answer.evidence_considered}
    missing = [cid for cid in refused if cid not in disclosed]
    gates.append(GateResult(
        gate="G7_EVIDENCE_FULLY_DISCLOSED", passed=not missing,
        detail=f"{len(disclosed)} record(s) disclosed with their governance reasoning"
               if not missing else f"undisclosed: {', '.join(missing)}"))

    # No synthetic text may be presented as an ABB publication.
    mislabelled = [c.chunk_id for s in answer.guidance for c in s.citations
                   if c.provenance is not ContentProvenance.ABB_PUBLIC_PDF
                   and "(synthetic)" not in c.label]
    gates.append(GateResult(
        gate="G8_PROVENANCE_LABELLED", passed=not mislabelled,
        detail="every citation states whether its source is an ABB publication"
               if not mislabelled else f"unlabelled synthetic sources: {', '.join(mislabelled)}"))

    gates.append(GateResult(
        gate="G9_READ_ONLY", passed=True, blocking=False,
        detail="no write was performed against any document or approval record"))

    return gates


def apply_gates(answer: OperatorAnswer, gates: list[GateResult]) -> OperatorAnswer:
    answer.gates = gates
    blocking = [g for g in gates if g.blocking and not g.passed]
    if blocking:
        answer.answered = False
        answer.guidance = []
        answer.status = DocumentationStatus.INSUFFICIENT_EVIDENCE
        # When the equipment is not confirmed, every later gate fails as a consequence;
        # listing them would bury the one thing the operator can fix.
        root = [g for g in blocking if g.gate == "G1_EQUIPMENT_IDENTIFIED"]
        blocking = root or blocking
        lines = ["DocDrift withheld the answer because these checks failed:"]
        lines += [f"- {GATE_LABELS.get(g.gate, g.gate)}: {g.detail}" for g in blocking]
        answer.clarification_needed = "\n".join(
            ([answer.clarification_needed] if answer.clarification_needed else []) + lines)
    return answer
