import json
import pathlib

from docdrift.evaluation import run_evaluation
from docdrift.models import ContentProvenance, DocumentationStatus
from tests.marks import needs_abb_text

M4 = "Drive M4 trips with fault 5091 after operating for ten minutes."


@needs_abb_text
def test_core_use_case(pipeline):
    answer, bundle = pipeline.ask(M4)
    assert answer.answered
    assert answer.equipment_summary.startswith("M4")
    assert answer.status is DocumentationStatus.POTENTIAL_APPROVED_UPDATE
    assert answer.guidance and all(s.citations for s in answer.guidance)
    assert "ECN-2026-011" in answer.pending_change
    assert any("T. Salonen" in e for e in answer.approval_evidence)
    assert any("Governance mode: strict" in e for e in answer.approval_evidence)
    assert answer.escalation and "cannot authorise" in answer.escalation
    cited = [pipeline.store.get_chunk(c.chunk_id)
             for s in answer.guidance for c in s.citations]
    current = {(r.doc_id, r.current.version) for r in bundle.versions}
    assert all((ch.doc_id, ch.version) in current for ch in cited)


@needs_abb_text
def test_guidance_is_grounded_in_real_abb_text(pipeline):
    answer, _ = pipeline.ask(M4)
    provs = {c.provenance for s in answer.guidance for c in s.citations}
    assert ContentProvenance.ABB_PUBLIC_PDF in provs


def test_unknown_equipment_asks_for_clarification(pipeline):
    answer, _ = pipeline.ask("The machine keeps stopping, what should I check?")
    assert not answer.answered and answer.clarification_needed
    assert answer.status is DocumentationStatus.INSUFFICIENT_EVIDENCE


@needs_abb_text
def test_audit_trail_records_every_examined_change(pipeline):
    pipeline.ask(M4)
    entry = json.loads(pathlib.Path(pipeline.settings.audit_path).read_text().strip().splitlines()[-1])
    assert entry["equipment"] == "M4"
    assert entry["governance_mode"] == "strict"
    assert entry["status"] == "Potential Approved Update"
    examined = {c["comm_id"]: c for c in entry["changes_examined"]}
    assert examined["ECN-2026-011"]["effective"] is True
    assert examined["C-4130"]["authority_state"] == "OUT_OF_SCOPE"
    assert all(g["passed"] for g in entry["gates"])


@needs_abb_text
def test_evaluation_set_passes(tmp_path):
    from docdrift.config import Settings
    settings = Settings()
    settings.audit_path = str(tmp_path / "eval.jsonl")
    results = run_evaluation(settings=settings)
    failures = [(r.case_id, r.mode, c.name, c.detail)
                for r in results for c in r.checks if not c.passed]
    assert not failures, failures
