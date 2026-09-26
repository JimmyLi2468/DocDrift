"""Governance core: decision state, authority state, and the conjunctive test a
change must pass before it is allowed to alter operating guidance.

A change alters guidance only if EVERY condition below holds. Any single failure
demotes it to evidence: it is still shown to the operator, with the reason, but it
cannot move the documentation status or the troubleshooting steps.

    C1 relevant to the question and the equipment
    C2 inside the freshness window (from the n-1 effective date)
    C3 a formal change record exists      <- governance policy, see GovernanceMode
    C4 the decision state is APPROVED
    C5 the approver identity is verified against personnel records
    C6 the approver holds authority for the scope of the change
    C7 that authority was valid on the decision date
    C8 the change is not already incorporated in the current version
    C9 the approval has not been invalidated by a later authorised decision

C3 is the only condition that is policy-configurable. In STRICT mode only a formal
change record can establish approval. In FLEXIBLE mode a direct approval from an
authorised person over Teams or email also counts - C5, C6 and C7 still apply, so
"flexible" relaxes the record requirement, never the authority requirement.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Channel(str, Enum):
    TEAMS_CHAT = "teams_chat"
    EMAIL = "email"
    FORMAL_CHANGE_NOTICE = "formal_change_notice"
    ENGINEERING_BULLETIN = "engineering_bulletin"
    MEETING_MINUTES = "meeting_minutes"


#: Channels that can carry a formal change record.
FORMAL_RECORD_CHANNELS = frozenset({Channel.FORMAL_CHANGE_NOTICE})

#: Channels on which a direct approval is admissible in FLEXIBLE mode.
FLEXIBLE_APPROVAL_CHANNELS = frozenset({Channel.TEAMS_CHAT, Channel.EMAIL,
                                        Channel.FORMAL_CHANGE_NOTICE})


class DecisionState(str, Enum):
    DISCUSSION = "DISCUSSION"
    PROPOSED = "PROPOSED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    # Reversal-only states: these never originate a change, they retire one.
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


#: A later decision in one of these states retires an earlier approval,
#: provided its author has authority for the scope (see `find_invalidations`).
INVALIDATING_STATES = frozenset({DecisionState.CANCELLED, DecisionState.REJECTED,
                                 DecisionState.WITHDRAWN, DecisionState.SUPERSEDED})


class AuthorityState(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"   # nothing was claimed that needs authority
    NOT_CHECKED = "NOT_CHECKED"         # discussion; no approval asserted
    VERIFIED = "VERIFIED"               # identified person, in scope, valid on the date
    UNVERIFIED = "UNVERIFIED"           # claimed approver not resolvable in personnel records
    OUT_OF_SCOPE = "OUT_OF_SCOPE"       # real person, real role, wrong scope
    EXPIRED = "EXPIRED"                 # authority did not cover the decision date


class GovernanceMode(str, Enum):
    STRICT = "strict"
    FLEXIBLE = "flexible"


# ------------------------------------------------------------------ authority model

class ApprovalScope(BaseModel):
    scope_id: str
    description: str


class RoleAuthority(BaseModel):
    """A role's authority over one scope, bounded in time so that delegations and
    role changes expire rather than lingering forever."""
    role: str
    scope_id: str
    valid_from: date
    valid_to: date | None = None
    delegation_of: str | None = None

    def covers(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day <= self.valid_to)


class AuthorityMatrix(BaseModel):
    scopes: list[ApprovalScope] = Field(default_factory=list)
    authorities: list[RoleAuthority] = Field(default_factory=list)

    def for_role(self, role: str, scope_id: str) -> list[RoleAuthority]:
        return [a for a in self.authorities if a.role == role and a.scope_id == scope_id]

    def evaluate(self, role: str | None, scope_id: str | None, day: date | None) -> tuple[AuthorityState, str]:
        if role is None:
            return AuthorityState.UNVERIFIED, "approver could not be resolved in personnel records"
        if scope_id is None:
            return AuthorityState.NOT_APPLICABLE, "the change declares no approval scope"
        entries = self.for_role(role, scope_id)
        if not entries:
            held = sorted({a.scope_id for a in self.authorities if a.role == role})
            return (AuthorityState.OUT_OF_SCOPE,
                    f"role '{role}' holds authority for {held or 'no scope'} but not for '{scope_id}'")
        if day is None:
            return AuthorityState.UNVERIFIED, "no decision date to validate the authority against"
        if not any(e.covers(day) for e in entries):
            windows = "; ".join(f"{e.valid_from} to {e.valid_to or 'open'}" for e in entries)
            return (AuthorityState.EXPIRED,
                    f"authority of '{role}' over '{scope_id}' did not cover {day} (valid {windows})")
        entry = next(e for e in entries if e.covers(day))
        via = f" (delegated from {entry.delegation_of})" if entry.delegation_of else ""
        return AuthorityState.VERIFIED, f"role '{role}' held '{scope_id}' authority on {day}{via}"


# ------------------------------------------------------------------ verdict

class ConditionResult(BaseModel):
    condition: str
    passed: bool
    detail: str


class GovernanceVerdict(BaseModel):
    comm_id: str
    change_ref: str | None = None
    mode: GovernanceMode
    decision_state: DecisionState
    authority_state: AuthorityState
    #: True only when every condition holds: the change may alter operating guidance.
    effective: bool = False
    conditions: list[ConditionResult] = Field(default_factory=list)
    invalidated_by: list[str] = Field(default_factory=list)

    @property
    def failed(self) -> list[str]:
        return [c.condition for c in self.conditions if not c.passed]

    @property
    def classification(self) -> str:
        """A single label for the operator-facing UI.

        Ordered by what the operator most needs to know first: a change that passed
        everything, then one that was retired, then the reason it was refused. The
        later conditions are only meaningful once the earlier ones held, so they are
        tested last.
        """
        failed = set(self.failed)
        if self.effective:
            return "effective_approved_change"
        if "C9_NOT_INVALIDATED" in failed:
            return "invalidated"
        if self.decision_state is DecisionState.PENDING_CONFIRMATION:
            return "pending_confirmation"
        if self.decision_state in (DecisionState.REJECTED, DecisionState.CANCELLED,
                                   DecisionState.WITHDRAWN, DecisionState.SUPERSEDED):
            return "closed_without_approval"
        if self.decision_state is not DecisionState.APPROVED:
            return "discovery_evidence"
        if self.authority_state is AuthorityState.EXPIRED:
            return "approval_authority_expired"
        if self.authority_state is not AuthorityState.VERIFIED:
            return "unauthorized_approval"
        if "C3_FORMAL_RECORD" in failed:
            return "approval_without_formal_record"
        if "C8_NOT_ALREADY_INCORPORATED" in failed:
            return "already_incorporated"
        if "C1_RELEVANT" in failed:
            return "not_relevant_to_question"
        if "C2_WITHIN_FRESHNESS_WINDOW" in failed:
            return "outside_freshness_window"
        return "refused"
