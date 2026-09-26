from docdrift.models import Citation, ContentProvenance, GuidanceStep
from docdrift.policy import apply_gates, run_gates
from docdrift.validate import validate_citation
from tests.marks import needs_abb_text

M4 = "Drive M4 trips with fault 5091 after operating for ten minutes."


def test_quote_must_exist_verbatim(pipeline):
    chunk = pipeline.store.chunks_for("3AXD50000016097", "J")[0]
    good = Citation(chunk_id=chunk.chunk_id, label=chunk.citation_label,
                    quote=" ".join(chunk.text.split())[:90], page=chunk.page,
                    provenance=chunk.provenance)
    bad = good.model_copy(update={"quote": "Bypass the safety circuit with a jumper."})
    assert validate_citation(good, pipeline.store)[0]
    assert not validate_citation(bad, pipeline.store)[0]


def test_superseded_revision_is_rejected_as_a_source(pipeline):
    chunk = pipeline.store.chunks_for("3AXD50000016097", "H")[0]
    cit = Citation(chunk_id=chunk.chunk_id, label=chunk.citation_label,
                   quote=" ".join(chunk.text.split())[:60], page=chunk.page,
                   provenance=chunk.provenance)
    ok, why = validate_citation(cit, pipeline.store)
    assert not ok and "not the current version" in why


@needs_abb_text
def test_gates_all_pass_on_the_core_scenario(pipeline):
    answer, _ = pipeline.ask(M4)
    assert [g.gate for g in answer.gates if not g.passed] == []
    assert answer.answered


def test_uncited_step_blocks_the_answer(pipeline):
    answer, bundle = pipeline.ask(M4)
    answer.guidance = [GuidanceStep(text="Do the thing.", citations=[])]
    answer = apply_gates(answer, run_gates(bundle, answer, pipeline.store,
                                           pipeline.settings.thresholds))
    assert not answer.answered and answer.clarification_needed


@needs_abb_text
def test_synthetic_text_cannot_be_presented_as_an_abb_publication(pipeline):
    answer, bundle = pipeline.ask(M4)
    answer.guidance[0].citations[0] = answer.guidance[0].citations[0].model_copy(
        update={"provenance": ContentProvenance.SYNTHETIC_HISTORICAL,
                "label": "3AXD50000016097 v J S556 p.556"})
    gates = {g.gate: g for g in run_gates(bundle, answer, pipeline.store,
                                          pipeline.settings.thresholds)}
    assert not gates["G8_PROVENANCE_LABELLED"].passed


def test_every_refused_record_is_still_disclosed(pipeline):
    answer, bundle = pipeline.ask(M4)
    refused = {c.communication.comm_id for c in bundle.candidate_changes if not c.effective}
    disclosed = {d.comm_id for d in answer.evidence_considered}
    assert refused <= disclosed
    assert all(d.failed_conditions for d in answer.evidence_considered
               if d.comm_id in refused)
