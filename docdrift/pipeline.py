"""End-to-end controller: question in, verified operator answer out."""
from __future__ import annotations

from .answer import build_answer
from .audit import record
from .config import Settings
from .rerank import rerank
from .drift import effective_changes, find_candidate_changes
from .entity import resolve_equipment
from .governance import AuthorityMatrix, GovernanceMode
from .ingest.operator_photo import PhotoExtraction, combine_with_question
from .models import DocumentationStatus, EvidenceBundle, OperatorAnswer
from .policy import apply_gates, run_gates
from .versioning import resolve_versions


class Pipeline:
    def __init__(self, store, graph, retriever, embedder, llm, authority: AuthorityMatrix,
                 settings: Settings, conversations=None) -> None:
        self.conversations = conversations
        self.store, self.graph, self.retriever = store, graph, retriever
        self.embedder, self.llm = embedder, llm
        self.authority, self.settings = authority, settings

    # ------------------------------------------------------------------ evidence
    def build_evidence(self, question: str, mode: GovernanceMode | None = None) -> EvidenceBundle:
        th = self.settings.thresholds
        mode = mode or self.settings.governance_mode
        match = resolve_equipment(question, self.store.all_equipment(), th)
        bundle = EvidenceBundle(question=question, equipment=match, mode=mode)
        if match.equipment is None:
            bundle.notes.append("equipment not resolved; retrieval not attempted")
            return bundle

        eq = match.equipment
        bundle.versions = resolve_versions(self.store, eq)
        current_keys = {(r.doc_id, r.current.version) for r in bundle.versions}
        # Metadata filter first: only documents the asset register assigns to this
        # machine are searched, so an asset documented by two pages is not crowded out
        # of the result list by a 120 page catalogue belonging to another line.
        # The asset's model is appended to the retrieval query so that, inside a
        # catalogue covering forty contactor frames, the pages about this one rank.
        query = f"{question} {eq.model} {eq.type_code or ''}".strip()
        hits = self.retriever.search(query, top_k=th.retrieval_candidates,
                                     where={"doc_id": [r.doc_id for r in bundle.versions]})
        current_hits = [h for h in hits if (h.chunk.doc_id, h.chunk.version) in current_keys]
        bundle.guidance_chunks = rerank(current_hits, question, eq, match.fault_codes,
                                        th.retrieval_top_k)
        if not bundle.guidance_chunks:
            bundle.notes.append("no passage in a current applicable document matched the question")

        docs_in_use = {h.chunk.doc_id for h in bundle.guidance_chunks}
        bundle.candidate_changes = find_candidate_changes(
            self.store, self.authority, self.embedder, eq, bundle.versions,
            question, match.fault_codes, th, mode, docs_in_use=docs_in_use)

        # Second, independent derivation of approver authority, from the knowledge
        # graph. The decision above used the authority records; G10 requires both to
        # agree, so a divergence between the two sources withholds the answer.
        for cand in bundle.candidate_changes:
            comm = cand.communication
            if comm.approver_person_id:
                day = str(comm.decision_date or comm.date)
                cand.authority_path = self.graph.authority_path(comm.comm_id, day)

        drifting = effective_changes(bundle.candidate_changes)
        other = effective_changes(bundle.candidate_changes, scope="asset_open_change")
        if other:
            bundle.notes.append(
                f"{len(other)} approved change(s) affect this asset but not the question asked: "
                + ", ".join(c.communication.comm_id for c in other))
        refused = [c for c in bundle.candidate_changes if not c.effective]
        if refused:
            bundle.notes.append(
                f"{len(refused)} record(s) examined and refused: "
                + ", ".join(f"{c.communication.comm_id}[{c.classification}]" for c in refused))

        if not bundle.guidance_chunks:
            bundle.status = DocumentationStatus.INSUFFICIENT_EVIDENCE
        elif drifting:
            bundle.status = DocumentationStatus.POTENTIAL_APPROVED_UPDATE
        else:
            bundle.status = DocumentationStatus.VERIFIED_CURRENT
        return bundle

    # ------------------------------------------------------------------ answer
    def ask(self, question: str, mode: GovernanceMode | None = None,
            photo: PhotoExtraction | None = None, session_id: str | None = None,
            turn_id: str | None = None) -> tuple[OperatorAnswer, EvidenceBundle]:
        combined = combine_with_question(question, photo)
        bundle = self.build_evidence(combined, mode=mode)
        if photo is not None:
            bundle.equipment.source = "text+photo"
        answer = build_answer(bundle, self.store, self.llm)
        answer = apply_gates(answer, run_gates(bundle, answer, self.store,
                                               self.settings.thresholds))
        if self.settings.audit_enabled:          # default off: nothing is written
            entry = record(self.settings.audit_path, combined, bundle, answer)
            if self.conversations is not None:
                import uuid
                self.conversations.append(turn_id or uuid.uuid4().hex, session_id or "cli",
                                          entry, answer)
        return answer, bundle
