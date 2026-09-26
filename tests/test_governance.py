"""The conjunctive test, one branch at a time."""
import pytest

from docdrift.governance import AuthorityState, DecisionState, GovernanceMode
from tests.marks import needs_abb_text

M4 = "Drive M4 trips with fault 5091 after operating for ten minutes."
K2_TORQUE = "What tightening torque do the main terminals of contactor K2 need?"
K2_COIL = "What are the coil operating limits for contactor K2?"
K2_TRIP = "What EOL trip class should softstarter S1 use?"
S2 = "What regular maintenance does the manual specify for softstarter S2?"
P5 = "Is a transformer protection breaker still required for P5?"


def changes(pipeline, question, mode=None):
    _, bundle = pipeline.ask(question, mode=mode)
    return {c.communication.comm_id: c for c in bundle.candidate_changes}


def test_all_conditions_hold_for_the_headline_change(pipeline):
    c = changes(pipeline, M4)["ECN-2026-011"]
    assert c.effective
    assert [x.condition for x in c.verdict.conditions if not x.passed] == []
    assert c.verdict.authority_state is AuthorityState.VERIFIED
    assert c.incorporation is not None and not c.incorporation.incorporated
    assert "ferrules" in c.incorporation.missing_terms


def test_authorised_person_but_approval_not_confirmed(pipeline):
    """Scenario 1: an Engineering Manager says he will confirm after the safety review."""
    c = changes(pipeline, K2_TRIP)["C-4121"]
    assert c.verdict.decision_state is DecisionState.PENDING_CONFIRMATION
    assert c.verdict.authority_state is AuthorityState.VERIFIED
    assert c.communication.formal_approval_record_id is None
    assert not c.effective
    assert "C4_DECISION_APPROVED" in c.verdict.failed
    assert c.classification == "pending_confirmation"


def test_approval_from_a_manager_without_authority(pipeline):
    """Scenario 2: a Procurement Manager writes "Approved" on a wiring change."""
    c = changes(pipeline, M4)["C-4130"]
    assert c.verdict.decision_state is DecisionState.APPROVED
    assert c.verdict.authority_state is AuthorityState.OUT_OF_SCOPE
    assert not c.effective
    assert "C6_AUTHORITY_IN_SCOPE" in c.verdict.failed
    assert c.classification == "unauthorized_approval"


def test_general_discussion_is_discovery_evidence_only(pipeline):
    """Scenario 3: technicians talking. Excluded before the incorporation comparison."""
    c = changes(pipeline, K2_TORQUE)["C-4140"]
    assert c.verdict.decision_state is DecisionState.DISCUSSION
    assert c.verdict.authority_state is AuthorityState.NOT_CHECKED
    assert not c.effective
    assert c.classification == "discovery_evidence"
    assert c.incorporation is None, "incorporation must not be computed for discussion"


def test_authority_that_had_expired_on_the_decision_date(pipeline):
    c = changes(pipeline, K2_COIL)["ECN-2026-031"]
    assert c.verdict.authority_state is AuthorityState.EXPIRED
    assert "C7_AUTHORITY_VALID_ON_DATE" in c.verdict.failed
    assert not c.effective


@needs_abb_text
def test_already_incorporated_change_raises_no_drift(pipeline):
    c = changes(pipeline, "Is Safe Torque Off a standard feature on the drive fitted to M4?")
    entry = c["ECN-2025-129"]
    assert entry.verdict.authority_state is AuthorityState.VERIFIED
    assert entry.incorporation is not None and entry.incorporation.incorporated
    assert not entry.effective


def test_later_cancellation_by_an_authorised_person_invalidates(pipeline):
    c = changes(pipeline, P5)["ECN-2026-027"]
    assert "C9_NOT_INVALIDATED" in c.verdict.failed
    assert "C-4150" in c.verdict.invalidated_by
    assert c.classification == "invalidated"


def test_cancellation_without_authority_does_not_invalidate(pipeline):
    c = changes(pipeline, K2_TORQUE)["ECN-2026-033"]
    assert c.effective, "a technician cannot cancel an approved engineering change"
    assert c.verdict.invalidated_by == []
    reason = next(x.detail for x in c.verdict.conditions if x.condition == "C9_NOT_INVALIDATED")
    assert "ignored" in reason and "C-4160" in reason


@pytest.mark.parametrize("mode,expected_effective", [(GovernanceMode.STRICT, False),
                                                     (GovernanceMode.FLEXIBLE, True)])
def test_governance_mode_controls_only_the_formal_record_condition(pipeline, mode, expected_effective):
    c = changes(pipeline, S2, mode=mode)["C-4111"]
    assert c.verdict.decision_state is DecisionState.APPROVED
    assert c.verdict.authority_state is AuthorityState.VERIFIED   # unchanged by mode
    assert c.effective is expected_effective
    if not expected_effective:
        assert c.verdict.failed == ["C3_FORMAL_RECORD"]


def test_flexible_mode_still_refuses_an_unauthorised_approval(pipeline):
    c = changes(pipeline, M4, mode=GovernanceMode.FLEXIBLE)["C-4130"]
    assert not c.effective
    assert "C6_AUTHORITY_IN_SCOPE" in c.verdict.failed
