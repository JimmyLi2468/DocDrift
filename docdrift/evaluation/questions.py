"""The evaluation set.

Each case states what DocDrift should conclude, not merely that it should answer.
Expectations are written against the governance outcome - which record was allowed
to alter guidance, and why every other record was refused - because that is the part
of the system that can be wrong in a way an operator would not notice.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    case_id: str
    question: str
    probes: str
    expect_asset: str | None
    #: governance mode -> expected documentation status
    expect_status: dict[str, str] = field(default_factory=dict)
    expect_answered: bool = True
    #: comm_id -> expected classification label
    expect_classifications: dict[str, str] = field(default_factory=dict)
    #: classifications that differ between governance modes
    expect_classifications_strict: dict[str, str] = field(default_factory=dict)
    expect_classifications_flexible: dict[str, str] = field(default_factory=dict)
    expect_effective: list[str] = field(default_factory=list)
    expect_not_effective: list[str] = field(default_factory=list)
    #: (doc_id, version) pairs that must never appear as a citation
    forbid_cited_versions: list[tuple[str, str]] = field(default_factory=list)
    require_abb_provenance: bool = False
    #: (doc_id, page) pairs of which at least one must be cited
    expect_cited_pages: list[tuple[str, int]] = field(default_factory=list)


PAU = "Potential Approved Update"
VC = "Verified Current"
IE = "Insufficient Evidence"

FW580 = "3AXD50000016097"
PSTX = "1SFC132081M0201"
AFCAT = "1SBC100214C0202"

EVAL_CASES: list[EvalCase] = [
    # ---- drives
    EvalCase("E01", "Drive M4 trips with fault 5091 after operating for ten minutes.",
             "the core use case: approved, formal, in scope, not yet in firmware manual rev J",
             "M4", {"strict": PAU, "flexible": PAU},
             expect_effective=["ECN-2026-011"],
             expect_classifications={"ECN-2026-011": "effective_approved_change",
                                     "ECN-2025-129": "already_incorporated",
                                     "C-4130": "unauthorized_approval",
                                     "C-4101": "discovery_evidence",
                                     "C-4102": "discovery_evidence"},
             forbid_cited_versions=[(FW580, "H")], require_abb_provenance=True,
             expect_cited_pages=[(FW580, 556)]),
    EvalCase("E02", "Where is fault 5091 Safe torque off configured on drive M7?",
             "same family, different asset: the same ECN applies because it is family-scoped",
             "M7", {"strict": PAU, "flexible": PAU}, expect_effective=["ECN-2026-011"],
             require_abb_provenance=True),
    EvalCase("E03", "Drive M9 shows fault 5091 Safe torque off, what should I check?",
             "same fault code on another family: an ACS580 change must not leak to ACS480",
             "M9", {"strict": VC, "flexible": VC}, expect_not_effective=["ECN-2026-011"],
             expect_classifications={"ECN-2025-071": "already_incorporated"},
             expect_cited_pages=[("3AXD50000047399", 539)], require_abb_provenance=True,
             forbid_cited_versions=[("3AXD50000047399", "F")]),
    EvalCase("E04", "What insulation resistance check does the manual give before first start of drive M9?",
             "an engineering bulletin is a supported channel but never an approval channel",
             "M9", {"strict": VC, "flexible": VC}, expect_not_effective=["EB-2026-020"],
             expect_classifications={"EB-2026-020": "approval_without_formal_record"}),
    EvalCase("E05", "Who approved the STO wiring kit for the M4 panel?",
             "a Procurement Manager's 'Approved' on a safety wiring change is out of scope",
             "M4", {}, expect_not_effective=["C-4130"],
             expect_classifications={"C-4130": "unauthorized_approval"}),

    # ---- softstarters
    EvalCase("E06", "What regular maintenance does the manual specify for softstarter S2?",
             "governance mode: an authorised Teams approval with no formal record",
             "S2", {"strict": VC, "flexible": PAU},
             expect_classifications_strict={"C-4111": "approval_without_formal_record"},
             expect_classifications_flexible={"C-4111": "effective_approved_change"},
             expect_cited_pages=[(PSTX, 150)], forbid_cited_versions=[(PSTX, "P")]),
    EvalCase("E07", "What EOL trip class should softstarter S1 use?",
             "authorised approver involved, approval not confirmed (pending safety review)",
             "S1", {"strict": VC, "flexible": VC}, expect_not_effective=["C-4121"],
             expect_classifications={"C-4121": "pending_confirmation"},
             expect_cited_pages=[(PSTX, 103)]),
    EvalCase("E08", "Softstarter S2 tripped on short circuit thyristor, what does the manual say?",
             "fault handling from the I&C manual; the maintenance change is disclosed in flexible mode",
             "S2", {"strict": VC}, require_abb_provenance=True),
    EvalCase("E09", "What start ramp time range can be set on softstarter S3?",
             "an asset with no change thread at all: verified current, nothing examined as effective",
             "S3", {"strict": VC, "flexible": VC}, require_abb_provenance=True),
    EvalCase("E10", "What regular maintenance applies to the PSTX142 on the mixer line?",
             "equipment identified from the model number alone",
             "S2", {"strict": VC, "flexible": PAU}),

    # ---- motor protection
    EvalCase("E11", "What tightening torque do the main terminals of contactor K2 need?",
             "approved change survives a 'cancellation' from a technician with no authority",
             "K2", {"strict": PAU, "flexible": PAU}, expect_effective=["ECN-2026-033"],
             expect_classifications={"ECN-2026-033": "effective_approved_change",
                                     "C-4160": "closed_without_approval",
                                     "C-4140": "discovery_evidence"},
             expect_cited_pages=[(AFCAT, 180)], forbid_cited_versions=[(AFCAT, "2023")]),
    EvalCase("E12", "What are the coil operating limits for contactor K2?",
             "approved under a delegation that had lapsed on the decision date",
             "K2", {"strict": VC, "flexible": VC}, expect_not_effective=["ECN-2026-031"],
             expect_classifications={"ECN-2026-031": "approval_authority_expired"},
             expect_cited_pages=[(AFCAT, 175)]),
    EvalCase("E13", "Should we be tightening the AF38 feeder contactor terminals harder than the book says?",
             "technician discussion is discovery evidence only; no incorporation check is run",
             "K2", {"strict": PAU}, expect_classifications={"C-4140": "discovery_evidence"}),
    EvalCase("E14", "Is a transformer protection breaker still required for P5?",
             "an approval cancelled later by someone with authority to cancel it",
             "P5", {"strict": VC, "flexible": VC}, expect_not_effective=["ECN-2026-027"],
             expect_classifications={"ECN-2026-027": "invalidated"}),
    EvalCase("E15", "What current setting range does the MS132-10T breaker have?",
             "equipment identified from the type code; data sheet is the current document",
             "P5", {"strict": VC, "flexible": VC}, require_abb_provenance=True),

    # ---- equipment resolution
    EvalCase("E16", "The machine keeps stopping, what should I check?",
             "no identifiable equipment: the answer is withheld and clarification requested",
             None, {"strict": IE, "flexible": IE}, expect_answered=False),
    EvalCase("E17", "Fault 5091 keeps coming back on the drive, what should I check?",
             "a fault code shared by three drives, no tag: ambiguity must not be guessed away",
             None, {"strict": IE, "flexible": IE}, expect_answered=False),
    EvalCase("E19", "How should the input cable shields of drive module M7 be grounded?",
             "an approved wiring change that ABB's rev F already carries: found via the n-1 window, refused as incorporated",
             "M7", {"strict": VC, "flexible": VC}, expect_not_effective=["ECN-2022-015"],
             expect_classifications={"ECN-2022-015": "already_incorporated"},
             forbid_cited_versions=[("3AXD50000015497", "E")]),
    EvalCase("E20", "How often should drive M4 get a drive inspection?",
             "approved inspection interval already stated in the current maintenance schedule",
             "M4", {"strict": VC, "flexible": VC}, expect_not_effective=["ECN-2025-102"],
             expect_classifications={"ECN-2025-102": "already_incorporated"},
             forbid_cited_versions=[("4FPS10000309652", "0")]),
    EvalCase("E18", "Drive M4 shows fault 5091 - is the approved STO wiring change in the manual yet?",
             "the operator asks the drift question directly",
             "M4", {"strict": PAU, "flexible": PAU}, expect_effective=["ECN-2026-011"]),
]
