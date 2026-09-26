"""Synthetic enterprise records: people, departments, approval authority, assets and
three months of communications.

Everything in this module is invented. It describes a fictional plant that happens to
operate real ABB equipment; it contains no ABB internal data and no real personnel.
The document layer it refers to is built separately in `registry.py` from the ABB
publications in data/library/. Every change thread below is anchored to a page of a
real current ABB document; the page numbers are asserted in tests/test_corpus.py.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..governance import (ApprovalScope, AuthorityMatrix, Channel, DecisionState,
                          RoleAuthority)
from ..abb_registry import AbbManifest, load_manifest
from ..models import (Chunk, Communication, Department, DocumentVersion, Equipment,
                      Person)
from .registry import build_registry, family_of

# ------------------------------------------------------------------ organisation

DEPARTMENTS = [
    Department(department_id="D-ENG", name="Plant Engineering", site="Plant 2"),
    Department(department_id="D-MNT", name="Maintenance", site="Plant 2"),
    Department(department_id="D-QA", name="Quality", site="Plant 2"),
    Department(department_id="D-DOC", name="Technical Documentation", site="Head office"),
    Department(department_id="D-PRC", name="Procurement", site="Head office"),
    Department(department_id="D-HSE", name="Health, Safety and Environment", site="Plant 2"),
]

PEOPLE = [
    Person(person_id="P-001", name="K. Lindqvist", role="Engineering Manager", department_id="D-ENG"),
    Person(person_id="P-002", name="M. Berg", role="Document Owner", department_id="D-DOC"),
    Person(person_id="P-003", name="R. Okafor", role="Maintenance Technician", department_id="D-MNT"),
    Person(person_id="P-004", name="S. Duarte", role="Reliability Engineer", department_id="D-ENG"),
    Person(person_id="P-005", name="A. Novak", role="Quality Manager", department_id="D-QA"),
    Person(person_id="P-006", name="T. Salonen", role="Chief Engineer", department_id="D-ENG"),
    Person(person_id="P-007", name="J. Alvarez", role="Procurement Manager", department_id="D-PRC"),
    Person(person_id="P-008", name="H. Weber", role="Safety Engineer", department_id="D-HSE"),
    Person(person_id="P-009", name="L. Mensah", role="Senior Electrical Engineer", department_id="D-ENG"),
    Person(person_id="P-010", name="N. Fischer", role="Maintenance Supervisor", department_id="D-MNT"),
    Person(person_id="P-011", name="C. Ibarra", role="Maintenance Technician", department_id="D-MNT"),
    Person(person_id="P-012", name="Y. Tanaka", role="Controls Engineer", department_id="D-ENG"),
    Person(person_id="P-013", name="E. Lund", role="Documentation Specialist", department_id="D-DOC"),
]

SCOPES = [
    ApprovalScope(scope_id="electrical_wiring", description="Control and power wiring specifications"),
    ApprovalScope(scope_id="motor_protection_settings", description="Overload, trip class and starter settings"),
    ApprovalScope(scope_id="drive_parameters", description="Drive parameter sets and firmware options"),
    ApprovalScope(scope_id="safety_function", description="Safety functions and safety circuits"),
    ApprovalScope(scope_id="mechanical_installation", description="Mounting, cooling and enclosure work"),
    ApprovalScope(scope_id="procurement_commercial", description="Purchasing, suppliers and commercial terms"),
    ApprovalScope(scope_id="documentation_control", description="Controlled document lifecycle"),
    ApprovalScope(scope_id="maintenance_procedures", description="Inspection intervals and maintenance tasks"),
]

AUTHORITIES = [
    RoleAuthority(role="Engineering Manager", scope_id="electrical_wiring", valid_from=date(2023, 1, 1)),
    RoleAuthority(role="Engineering Manager", scope_id="motor_protection_settings", valid_from=date(2023, 1, 1)),
    RoleAuthority(role="Engineering Manager", scope_id="drive_parameters", valid_from=date(2023, 1, 1)),
    RoleAuthority(role="Engineering Manager", scope_id="mechanical_installation", valid_from=date(2023, 1, 1)),
    RoleAuthority(role="Chief Engineer", scope_id="electrical_wiring", valid_from=date(2022, 6, 1)),
    RoleAuthority(role="Chief Engineer", scope_id="motor_protection_settings", valid_from=date(2022, 6, 1)),
    RoleAuthority(role="Chief Engineer", scope_id="drive_parameters", valid_from=date(2022, 6, 1)),
    RoleAuthority(role="Chief Engineer", scope_id="safety_function", valid_from=date(2022, 6, 1)),
    RoleAuthority(role="Chief Engineer", scope_id="maintenance_procedures", valid_from=date(2022, 6, 1)),
    RoleAuthority(role="Engineering Manager", scope_id="maintenance_procedures", valid_from=date(2023, 1, 1)),
    RoleAuthority(role="Safety Engineer", scope_id="safety_function", valid_from=date(2024, 3, 1)),
    RoleAuthority(role="Quality Manager", scope_id="documentation_control", valid_from=date(2023, 1, 1)),
    RoleAuthority(role="Document Owner", scope_id="documentation_control", valid_from=date(2021, 1, 1)),
    RoleAuthority(role="Procurement Manager", scope_id="procurement_commercial", valid_from=date(2023, 1, 1)),
    # A delegation that has since lapsed - the basis of the "authority expired" case.
    RoleAuthority(role="Senior Electrical Engineer", scope_id="electrical_wiring",
                  valid_from=date(2026, 1, 5), valid_to=date(2026, 2, 28),
                  delegation_of="Engineering Manager"),
]

DOC_OWNERS = {"drives": "P-002", "softstarters": "P-002", "motor_protection": "P-005"}

# ------------------------------------------------------------------ assets
#
# One asset per library bundle. `type_code` is the ordering code the user downloaded
# documentation for; `model` is the base type code an operator would say.

EQUIPMENT = [
    Equipment(asset_tag="M4", name="Line 2 supply fan drive", model="ACS580-01", family="ACS580",
              category="drives", type_code="ACS580-01", library_bundle="ACH580-01",
              serial="SN-580-41190", firmware="ASCD2 2.2x", site="Plant 2", line="L2",
              commissioned=date(2022, 3, 18)),
    Equipment(asset_tag="M7", name="Line 3 extraction fan drive module", model="ACS580-04",
              family="ACS580", category="drives", type_code="ACS580-04",
              library_bundle="ACS580-04", serial="SN-580-72204", firmware="ASCD4 2.2x",
              site="Plant 2", line="L3", commissioned=date(2023, 6, 2)),
    Equipment(asset_tag="M9", name="Packing line machinery drive", model="ACS480", family="ACS480",
              category="drives", type_code="ACS480", library_bundle="ACS480",
              serial="SN-480-11907", firmware="ASDKA 2.2x", site="Plant 2", line="L4",
              commissioned=date(2024, 1, 15)),
    Equipment(asset_tag="S1", name="Line 1 belt conveyor softstarter", model="PSTX30", family="PSTX",
              category="softstarters", type_code="PSTX30-600-70", library_bundle="PSTX30-600-70",
              serial="SN-PSTX-30881", site="Plant 2", line="L1", commissioned=date(2021, 9, 7)),
    Equipment(asset_tag="S2", name="Line 2 mixer softstarter", model="PSTX142", family="PSTX",
              category="softstarters", type_code="PSTX142-600-70",
              library_bundle="PSTX142-600-70", serial="SN-PSTX-14226", site="Plant 2",
              line="L2", commissioned=date(2022, 11, 21)),
    Equipment(asset_tag="S3", name="Coolant pump softstarter", model="PSR25", family="PSR",
              category="softstarters", type_code="PSR25-600-70", library_bundle="PSR25-600-70",
              serial="SN-PSR-25514", site="Plant 2", line="L2", commissioned=date(2021, 4, 12)),
    Equipment(asset_tag="P5", name="Control transformer primary breaker", model="MS132-10T",
              family="MS132", category="motor_protection", type_code="MS132-10T",
              library_bundle="MS132-10T", serial="SN-MS-13210", site="Plant 2", line="L1",
              commissioned=date(2020, 8, 30)),
    Equipment(asset_tag="K2", name="Line 1 conveyor feeder contactor", model="AF38", family="AF",
              category="motor_protection", type_code="AF38-30-00-13",
              library_bundle="AF38-30-00-13", serial="SN-AF-38207", site="Plant 2", line="L1",
              commissioned=date(2020, 8, 30)),
]

#: Publications that apply across a whole family regardless of which bundle they were
#: downloaded into - one firmware manual serves every drive of that family.
FAMILY_WIDE_TYPES = {"firmware_manual"}


def title_excludes(title: str, eq: Equipment) -> bool:
    import re as _re
    base = _re.match(r"^([A-Z]+)(\d+)", eq.model)
    if not base:
        return False
    prefix, n = base.group(1), int(base.group(2))
    ranges = _re.findall(r"(?<![A-Za-z])" + _re.escape(prefix) + r"(\d+)\s?(?:\.\.\.|…)\s?"
                         + "(?:" + _re.escape(prefix) + r")?(\d+)", title)
    return bool(ranges) and not any(int(a) <= n <= int(b) for a, b in ranges)


def assign_documents(equipment: list[Equipment], manifest: AbbManifest) -> list[Equipment]:
    """Link every asset to the ABB publications that apply to it.

    A publication applies to an asset when it was downloaded for that asset (it sits
    in the asset's bundle) and does not name only other product families, or when it
    names the asset's exact model, or when it is a family-wide document such as the
    firmware manual. The result is stored on the asset register, which is what the
    pipeline treats as authoritative.
    """
    out = []
    for eq in equipment:
        linked: list[str] = []
        for rec in manifest.documents:
            # Operator guidance is given in English. German and multilingual
            # publications stay in the library and the manifest but are not linked.
            if rec.language != "en":
                continue
            families = {family_of(m) for m in rec.covers_models}
            # A title that scopes the publication to a frame range ("Softstarters Type
            # PSTX1050...1250") is decisive: outside that range it does not apply, however
            # often the body text mentions other frames.
            if title_excludes(rec.title, eq):
                continue
            in_bundle = eq.library_bundle in rec.bundles
            names_only_others = bool(families) and eq.family not in families
            exact = eq.model in rec.covers_models
            family_wide = rec.doc_type in FAMILY_WIDE_TYPES and eq.family in families
            if (in_bundle and not names_only_others) or exact or family_wide:
                linked.append(rec.doc_key)
        out.append(eq.model_copy(update={"doc_ids": linked}))
    return out


# ------------------------------------------------------------------ change threads
#
# Every thread is anchored to a real page of a current ABB publication:
#
#   3AXD50000016097  ACS580 firmware manual rev J    p.556  fault 5091 Safe torque off
#   1SFC132081M0201  PSTX I&C manual rev Q           p.150  9.1 Regular maintenance
#                                                     p.120  short circuit thyristor fault
#                                                     p.103  13.02 EOL class
#   1SBC100214C0202  Motor protection main cat. 2024 p.180  AF26...AF38 tightening torque
#                                                     p.175  AF09...AF38 coil operating limits
#   2CDC131058D0201  MS132-T data sheet rev D        p.1    transformer primary protection
#   3AXD50000047392  ACS480 hardware manual rev F    p.64   insulation resistance
#
# The normative terms of each change were checked to be absent from those pages, so
# the incorporation test has a real negative to find.

FW580 = "3AXD50000016097"
PSTX_MAN = "1SFC132081M0201"
AF_CAT = "1SBC100214C0202"
MS_T = "2CDC131058D0201"
HW480 = "3AXD50000047392"
ACS580 = ["ACS580"]


def _c(**kw) -> Communication:
    return Communication(**kw)


SCENARIO_COMMS: list[Communication] = [
    # --- CHG-2026-011  The headline drift case: formal, approved by a Chief Engineer
    #     who holds safety-function authority, not yet in rev J.
    _c(comm_id="C-4101", channel=Channel.TEAMS_CHAT, date=date(2026, 5, 12),
       subject="M4 trips on 5091 about ten minutes into every run",
       body=("M4 trips with fault 5091 Safe torque off roughly ten minutes after start, always "
             "once the panel has warmed up. Reset clears it until the next warm-up. The safety "
             "relay never drops, so I think it is the X4 STO wiring rather than the circuit."),
       author_person_id="P-003", change_ref="CHG-2026-011",
       decision_state=DecisionState.DISCUSSION, equipment_families=ACS580, fault_codes=["5091"]),
    _c(comm_id="C-4102", channel=Channel.MEETING_MINUTES, date=date(2026, 5, 20),
       subject="Reliability review - intermittent 5091 Safe torque off on ACS580 drives",
       body=("Six intermittent 5091 Safe torque off trips this quarter on M4 and M7, all after "
             "warm-up. Proposal tabled: terminate STO conductors at X4 with ferrules, use "
             "shielded twisted pair for STO runs longer than 10 m, and retorque X4 at the next "
             "planned stop. To be raised as a change notice. No approval given at this meeting."),
       author_person_id="P-004", change_ref="CHG-2026-011",
       decision_state=DecisionState.PROPOSED, scope_id="safety_function",
       affects_doc_ids=[FW580], affects_sections=["556"], equipment_families=ACS580,
       fault_codes=["5091"]),
    _c(comm_id="ECN-2026-011", channel=Channel.FORMAL_CHANGE_NOTICE, date=date(2026, 6, 3),
       subject="ECN-2026-011 STO wiring at X4 on ACS580 drives with intermittent fault 5091",
       body=("Approved change to the troubleshooting of fault 5091 Safe torque off. Where 5091 "
             "recurs after warm-up, the STO conductors at X4 shall be terminated with ferrules "
             "and the X4 terminals retorqued. STO circuit runs longer than 10 m shall use "
             "shielded twisted pair. Apply at the next planned stop."),
       author_person_id="P-004", change_ref="CHG-2026-011",
       decision_state=DecisionState.APPROVED, approver_person_id="P-006",
       decision_date=date(2026, 6, 3), formal_approval_record_id="PLM-CR-51120",
       scope_id="safety_function", affects_doc_ids=[FW580], affects_sections=["556"],
       equipment_families=ACS580, fault_codes=["5091"],
       normative_terms=["ferrules", "retorqued", "shielded twisted pair"],
       references_comm_ids=["C-4102"]),

    # --- CHG-2025-129  Approved between the n-1 reconstruction and rev J, and carried
    #     into rev J. Found only because the window opens at n-1; refused as incorporated.
    _c(comm_id="ECN-2025-129", channel=Channel.FORMAL_CHANGE_NOTICE, date=date(2025, 6, 10),
       subject="ECN-2025-129 Document the programmable response of fault 5091",
       body=("Approved change: the fault table must state that 5091 Safe torque off is a "
             "programmable fault set by parameter 31.22 STO indication run/stop."),
       author_person_id="P-012", change_ref="CHG-2025-129",
       decision_state=DecisionState.APPROVED, approver_person_id="P-001",
       decision_date=date(2025, 6, 10), formal_approval_record_id="PLM-CR-49880",
       scope_id="drive_parameters", affects_doc_ids=[FW580], affects_sections=["556"],
       equipment_families=ACS580, fault_codes=["5091"],
       normative_terms=["31.22 STO indication run/stop"]),

    # --- Approved changes that ABB's next revision already carries. Each has a
    #     reconstructed n-1 revision, so the window finds it and the incorporation test
    #     refuses it: these are what most real change traffic looks like.
    _c(comm_id="ECN-2025-071", channel=Channel.FORMAL_CHANGE_NOTICE, date=date(2025, 3, 18),
       subject="ECN-2025-071 Add control board supply check to fault 5091 on ACS480",
       body=("Approved change: the ACS480 fault 5091 Safe torque off entry shall direct the "
             "technician to check parameter 95.04 Control board supply."),
       author_person_id="P-012", change_ref="CHG-2025-071",
       decision_state=DecisionState.APPROVED, approver_person_id="P-006",
       decision_date=date(2025, 3, 18), formal_approval_record_id="PLM-CR-48112",
       scope_id="drive_parameters", affects_doc_ids=["3AXD50000047399"], affects_sections=["539"],
       equipment_families=["ACS480"], fault_codes=["5091"],
       normative_terms=["95.04 Control board supply"]),
    _c(comm_id="ECN-2022-015", channel=Channel.FORMAL_CHANGE_NOTICE, date=date(2022, 7, 12),
       subject="ECN-2022-015 360-degree grounding of input cable shields, ACS580-04 modules",
       body=("Approved change: input cable shields of ACS580-04 drive modules shall be "
             "grounded 360° at the entry plate of the enclosure."),
       author_person_id="P-009", change_ref="CHG-2022-015",
       decision_state=DecisionState.APPROVED, approver_person_id="P-006",
       decision_date=date(2022, 7, 12), formal_approval_record_id="PLM-CR-40277",
       scope_id="electrical_wiring", affects_doc_ids=["3AXD50000015497"], affects_sections=["124"],
       equipment_families=["ACS580"], normative_terms=["cable shields 360°"]),
    _c(comm_id="ECN-2025-102", channel=Channel.FORMAL_CHANGE_NOTICE, date=date(2025, 11, 20),
       subject="ECN-2025-102 Annual inspection interval for ACS580 drives",
       body=("Approved change: ACS580 drives shall be inspected annually, as recommended in "
             "ABB's maintenance schedule. Adopt the schedule's annual drive inspections."),
       author_person_id="P-004", change_ref="CHG-2025-102",
       decision_state=DecisionState.APPROVED, approver_person_id="P-001",
       decision_date=date(2025, 11, 20), formal_approval_record_id="PLM-CR-50361",
       scope_id="maintenance_procedures", affects_doc_ids=["4FPS10000309652"],
       affects_sections=["1"], equipment_families=["ACS580"],
       normative_terms=["annual drive inspections"]),

    # --- CHG-2026-021  "Approved" from a Procurement Manager on the same STO wiring.
    _c(comm_id="C-4130", channel=Channel.EMAIL, date=date(2026, 6, 24),
       subject="Approved - STO wiring kit for the ACS580 panels",
       body=("Approved. Go ahead with the supplier's pre-terminated STO wiring kit for X4 on the "
             "ACS580 panels and have the manual updated to match."),
       author_person_id="P-007", change_ref="CHG-2026-021",
       decision_state=DecisionState.APPROVED, approver_person_id="P-007",
       decision_date=date(2026, 6, 24), formal_approval_record_id="PO-2026-8842",
       scope_id="safety_function", affects_doc_ids=[FW580], affects_sections=["556"],
       equipment_families=ACS580, fault_codes=["5091"],
       normative_terms=["pre-terminated STO wiring kit"]),

    # --- CHG-2026-014  Authorised approval given in Teams with no formal record.
    #     STRICT refuses it on C3 alone; FLEXIBLE accepts it.
    _c(comm_id="C-4110", channel=Channel.EMAIL, date=date(2026, 6, 11),
       subject="Bypass contactor inspection on S2 after the short circuit thyristor trip",
       body=("S2 tripped on short circuit thyristor (F0900) and we ran on two controlled phases "
             "for a shift. The regular maintenance in the manual gives no interval. I would like "
             "the softstarter and its bypass contactor inspected at a 6 month interval, plus a "
             "post-event inspection after any short circuit thyristor fault."),
       author_person_id="P-010", change_ref="CHG-2026-014",
       decision_state=DecisionState.PROPOSED, scope_id="maintenance_procedures",
       affects_doc_ids=[PSTX_MAN], affects_sections=["150", "120"],
       equipment_families=["PSTX"]),
    _c(comm_id="C-4111", channel=Channel.TEAMS_CHAT, date=date(2026, 6, 12),
       subject="Re: Bypass contactor inspection on S2 after the short circuit thyristor trip",
       body=("Approved. Add to the PSTX regular maintenance: inspect the softstarter at a 6 month "
             "interval and add a post-event inspection of the bypass contactor after any short "
             "circuit thyristor fault. I will have it written up as a change notice later."),
       author_person_id="P-006", change_ref="CHG-2026-014",
       decision_state=DecisionState.APPROVED, approver_person_id="P-006",
       decision_date=date(2026, 6, 12), formal_approval_record_id=None,
       scope_id="maintenance_procedures", affects_doc_ids=[PSTX_MAN],
       affects_sections=["150", "120"], equipment_families=["PSTX"],
       normative_terms=["6 month interval", "post-event inspection"],
       references_comm_ids=["C-4110"]),

    # --- CHG-2026-018  Authorised approver involved, approval not confirmed.
    _c(comm_id="C-4120", channel=Channel.TEAMS_CHAT, date=date(2026, 6, 18),
       subject="EOL trip class on the S1 belt conveyor softstarter",
       body=("S1 trips on electronic overload when the belt starts loaded after a weekend. "
             "Proposing we change parameter 13.02 EOL class from 10 to 20 on S1."),
       author_person_id="P-004", change_ref="CHG-2026-018",
       decision_state=DecisionState.PROPOSED, scope_id="motor_protection_settings",
       affects_doc_ids=[PSTX_MAN], affects_sections=["103"], equipment_families=["PSTX"],
       equipment_models=["PSTX30"]),
    _c(comm_id="C-4121", channel=Channel.TEAMS_CHAT, date=date(2026, 6, 18),
       subject="Re: EOL trip class on the S1 belt conveyor softstarter",
       body="This looks reasonable; let me confirm after the safety review.",
       author_person_id="P-001", change_ref="CHG-2026-018",
       decision_state=DecisionState.PENDING_CONFIRMATION, approver_person_id="P-001",
       decision_date=date(2026, 6, 18), formal_approval_record_id=None,
       scope_id="motor_protection_settings", affects_doc_ids=[PSTX_MAN],
       affects_sections=["103"], equipment_families=["PSTX"], equipment_models=["PSTX30"],
       normative_terms=["EOL class 20"], references_comm_ids=["C-4120"]),

    # --- CHG-2026-024  Technicians discussing torque. Discovery evidence only.
    _c(comm_id="C-4140", channel=Channel.TEAMS_CHAT, date=date(2026, 7, 2),
       subject="Main terminal torque on the L1 feeder contactors",
       body=("Anyone else finding loose main terminals on the AF38 feeder contactors on L1? I "
             "think we should be tightening them harder than the catalogue torque."),
       author_person_id="P-003", change_ref="CHG-2026-024",
       decision_state=DecisionState.DISCUSSION, equipment_families=["AF"],
       affects_doc_ids=[AF_CAT], affects_sections=["180"], normative_terms=["tighten harder"]),
    _c(comm_id="C-4141", channel=Channel.TEAMS_CHAT, date=date(2026, 7, 2),
       subject="Re: Main terminal torque on the L1 feeder contactors",
       body="Same on the L1 feeders. We should raise it with engineering rather than just doing it.",
       author_person_id="P-011", change_ref="CHG-2026-024",
       decision_state=DecisionState.DISCUSSION, equipment_families=["AF"],
       references_comm_ids=["C-4140"]),

    # --- CHG-2026-033  Approved; a technician's "cancellation" has no authority.
    _c(comm_id="ECN-2026-033", channel=Channel.FORMAL_CHANGE_NOTICE, date=date(2026, 5, 28),
       subject="ECN-2026-033 Main terminal tightening check for AF26...AF38 feeder contactors",
       body=("Approved change: main terminals of AF26...AF38 contactors on the L1 feeders are "
             "tightened to the catalogue torque with a calibrated torque tool, with a re-torque "
             "check after the first 500 operating hours."),
       author_person_id="P-009", change_ref="CHG-2026-033",
       decision_state=DecisionState.APPROVED, approver_person_id="P-001",
       decision_date=date(2026, 5, 28), formal_approval_record_id="PLM-CR-51099",
       scope_id="electrical_wiring", affects_doc_ids=[AF_CAT], affects_sections=["180"],
       equipment_families=["AF"], equipment_models=["AF38"],
       normative_terms=["calibrated torque", "re-torque", "500 operating hours"]),
    _c(comm_id="C-4160", channel=Channel.TEAMS_CHAT, date=date(2026, 7, 8),
       subject="Stopping ECN-2026-033 on the L1 feeders",
       body=("We are not doing ECN-2026-033 on the L1 feeders, we do not have a calibrated tool "
             "that small. Treat it as cancelled for our area."),
       author_person_id="P-003", change_ref="CHG-2026-033",
       decision_state=DecisionState.CANCELLED, approver_person_id="P-003",
       decision_date=date(2026, 7, 8), scope_id="electrical_wiring",
       affects_doc_ids=[AF_CAT], affects_sections=["180"], equipment_families=["AF"],
       references_comm_ids=["ECN-2026-033"]),

    # --- CHG-2026-031  Approved under a delegation that had lapsed on the decision date.
    _c(comm_id="ECN-2026-031", channel=Channel.FORMAL_CHANGE_NOTICE, date=date(2026, 3, 12),
       subject="ECN-2026-031 Tighter coil supply band for AF38 contactors on L1",
       body=("Approved change: the L1 control supply for AF09...AF38 contactor coils shall be "
             "held between 0.9 x Uc and 1.05 x Uc, tighter than the catalogue coil operating "
             "limits, because of repeated chatter on weak supply."),
       author_person_id="P-009", change_ref="CHG-2026-031",
       decision_state=DecisionState.APPROVED, approver_person_id="P-009",
       decision_date=date(2026, 3, 12), formal_approval_record_id="PLM-CR-50410",
       scope_id="electrical_wiring", affects_doc_ids=[AF_CAT], affects_sections=["175"],
       equipment_families=["AF"], normative_terms=["0.9 x Uc", "1.05 x Uc"]),

    # --- CHG-2026-027  Approved, then cancelled by someone who has the authority.
    _c(comm_id="ECN-2026-027", channel=Channel.FORMAL_CHANGE_NOTICE, date=date(2026, 6, 5),
       subject="ECN-2026-027 Standard MS132 on transformer primaries",
       body=("Approved change: a standard MS132 manual motor starter may be used on control "
             "transformer primaries on L1 in place of the MS132-T transformer protection "
             "breaker where the measured inrush is below eight times rated current."),
       author_person_id="P-009", change_ref="CHG-2026-027",
       decision_state=DecisionState.APPROVED, approver_person_id="P-001",
       decision_date=date(2026, 6, 5), formal_approval_record_id="PLM-CR-51166",
       scope_id="motor_protection_settings", affects_doc_ids=[MS_T], affects_sections=["1"],
       equipment_families=["MS132"], normative_terms=["eight times rated current"]),
    _c(comm_id="C-4150", channel=Channel.EMAIL, date=date(2026, 6, 27),
       subject="Cancelling ECN-2026-027",
       body=("Cancelling ECN-2026-027. The inrush measurements on L1 do not support it; the "
             "MS132-T transformer protection breakers stay mandatory on transformer primaries."),
       author_person_id="P-006", change_ref="CHG-2026-027",
       decision_state=DecisionState.CANCELLED, approver_person_id="P-006",
       decision_date=date(2026, 6, 27), formal_approval_record_id="PLM-CR-51166",
       scope_id="motor_protection_settings", affects_doc_ids=[MS_T], affects_sections=["1"],
       equipment_families=["MS132"], references_comm_ids=["ECN-2026-027"]),

    # --- CHG-2026-020  An engineering bulletin: a supported channel, never an approval channel.
    _c(comm_id="EB-2026-020", channel=Channel.ENGINEERING_BULLETIN, date=date(2026, 6, 16),
       subject="Engineering bulletin 2026-020 ACS480 commissioning checklist",
       body=("Approved for issue: the ACS480 commissioning checklist adds a recorded insulation "
             "resistance measurement of the motor cable before first start, with the value "
             "entered in the asset record."),
       author_person_id="P-006", change_ref="CHG-2026-020",
       decision_state=DecisionState.APPROVED, approver_person_id="P-006",
       decision_date=date(2026, 6, 16), formal_approval_record_id=None,
       scope_id="drive_parameters", affects_doc_ids=[HW480], affects_sections=["64"],
       equipment_families=["ACS480"], normative_terms=["entered in the asset record"]),
]

#: Anchors asserted against the real document text in tests/test_corpus.py.
ANCHORS = {
    (FW580, 556): "5091 Safe torque off",
    (PSTX_MAN, 150): "9.1 Regular maintenance",
    (PSTX_MAN, 120): "shorted",
    (PSTX_MAN, 103): "EOL class",
    (AF_CAT, 180): "Tightening torque",
    (AF_CAT, 175): "Coil operating limits",
    (MS_T, 1): "primary side",
    (HW480, 64): "nsulation",
}

# ------------------------------------------------------------------ background traffic

FILLER_TEMPLATES = [
    ("Spares check for {tag}", "Do we hold a spare for {tag} ({model}) on site? The stores list is out of date."),
    ("Shift handover note - {line}", "{tag} ran clean all shift. Nothing outstanding on {line}."),
    ("Planned stop scheduling", "Proposing the {line} planned stop moves a week later so we can do {tag} at the same time."),
    ("Panel thermography results", "Thermography on {line} came back clean apart from a warm termination near {tag}. Re-check next round."),
    ("Training request", "Two technicians would like the manufacturer course before we take on more {model} units."),
    ("Vibration trend on {tag}", "Vibration trend on {tag} is flat this month. No action."),
    ("Cleaning schedule", "Filter cleaning on the {line} panels is moving to a four week cycle."),
    ("Spare panel meters", "Panel meters for {line} are on back order, expected next month."),
    ("Weekly maintenance summary", "Three corrective jobs on {line} this week, none related to {tag}."),
    ("Contractor access", "Contractor access for the {line} shutdown is booked. No documentation changes needed."),
    ("Calibration due", "Torque wrenches used on the {line} panels are due for calibration this month."),
    ("Energy report", "Energy use on {line} is down slightly after the {tag} setpoint review."),
]


def _filler(rng: random.Random, start: date, days: int, n: int,
            equipment: list[Equipment]) -> list[Communication]:
    """Routine plant traffic. None of it carries a decision or an approval."""
    people = [p.person_id for p in PEOPLE if p.department_id in ("D-MNT", "D-ENG")]
    channels = [Channel.TEAMS_CHAT] * 6 + [Channel.EMAIL] * 3 + [Channel.MEETING_MINUTES]
    out = []
    for i in range(n):
        eq = rng.choice(equipment)
        subject, body = rng.choice(FILLER_TEMPLATES)
        fmt = {"tag": eq.asset_tag, "model": eq.model, "line": eq.line or eq.site}
        out.append(Communication(
            comm_id=f"C-{5000 + i}", channel=rng.choice(channels),
            date=start + timedelta(days=rng.randrange(days)),
            subject=subject.format(**fmt), body=body.format(**fmt),
            author_person_id=rng.choice(people),
            decision_state=DecisionState.DISCUSSION,
            equipment_families=[eq.family], equipment_models=[eq.model]))
    return sorted(out, key=lambda c: c.date)


#: Plain-language change descriptions shown on the operator page ("Change description").
CHANGE_SUMMARIES = {
    "ECN-2026-011": "Terminate the STO conductors at X4 with ferrules and re-torque the X4 terminals "
                    "when fault 5091 recurs after warm-up; use shielded twisted pair for STO runs over 10 m.",
    "ECN-2025-129": "State in the fault table that 5091 is a programmable fault set by parameter 31.22.",
    "ECN-2025-071": "Add a check of parameter 95.04 Control board supply to the ACS480 fault 5091 entry.",
    "ECN-2022-015": "Ground the ACS580-04 input cable shields 360° at the enclosure entry plate.",
    "ECN-2025-102": "Inspect ACS580 drives once a year.",
    "C-4130": "Use the supplier's pre-terminated STO wiring kit on the ACS580 panels.",
    "C-4111": "Inspect PSTX softstarters every 6 months, and inspect the bypass contactor after any "
              "short circuit thyristor fault.",
    "C-4121": "Not a decision: a tentative reply to the proposal (C-4120) to change S1 parameter "
              "13.02 EOL class from 10 to 20, deferred until after the safety review.",
    "ECN-2026-033": "Tighten AF26...AF38 main terminals with a calibrated torque tool and re-check the "
                    "torque after the first 500 operating hours.",
    "ECN-2026-031": "Hold the AF09...AF38 coil supply between 0.9 and 1.05 x Uc, tighter than the catalogue limits.",
    "ECN-2026-027": "Allow a standard MS132 starter instead of the MS132-T on transformer primaries where "
                    "inrush is below 8 x rated current.",
    "EB-2026-020": "Record a motor-cable insulation resistance measurement before the first start of ACS480 drives.",
}


def _summary(comm: Communication) -> str:
    if comm.comm_id in CHANGE_SUMMARIES:
        return CHANGE_SUMMARIES[comm.comm_id]
    return re.sub(r"^(ECN|EB|CHG)-\d{4}-\d+\s*", "", comm.subject).strip()


# ------------------------------------------------------------------ assembly

@dataclass
class Corpus:
    departments: list[Department] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    equipment: list[Equipment] = field(default_factory=list)
    versions: list[DocumentVersion] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    communications: list[Communication] = field(default_factory=list)
    authority: AuthorityMatrix = field(default_factory=AuthorityMatrix)

    def summary(self) -> dict[str, int]:
        return {
            "product_categories": len({e.category for e in self.equipment}),
            "equipment_models": len({e.model for e in self.equipment}),
            "abb_documents": sum(1 for v in self.versions if v.status == "current"),
            "abb_pages_indexed": len({(c.doc_id, c.page) for c in self.chunks
                                      if c.provenance.value == "abb_public_pdf"}),
            "synthetic_historical_versions": sum(1 for v in self.versions if v.status == "superseded"),
            "communications": len(self.communications),
            "change_notices": sum(1 for c in self.communications
                                  if c.channel is Channel.FORMAL_CHANGE_NOTICE),
            "personnel": len(self.people),
            "departments": len(self.departments),
            "approval_scopes": len(self.authority.scopes),
            "authority_rows": len(self.authority.authorities),
            "chunks": len(self.chunks),
        }


def build_corpus(seed: int = 20260922, filler_count: int = 42,
                 chunk_cache: dict | None = None, manifest: AbbManifest | None = None) -> Corpus:
    manifest = manifest or load_manifest()
    versions, chunks = build_registry(manifest=manifest, chunk_cache=chunk_cache,
                                      owners=DOC_OWNERS)
    equipment = assign_documents(EQUIPMENT, manifest)
    rng = random.Random(seed)
    comms = [c.model_copy(update={"summary": c.summary or _summary(c)})
             for c in SCENARIO_COMMS + _filler(rng, date(2026, 5, 1), 92, filler_count, equipment)]
    return Corpus(
        departments=DEPARTMENTS, people=PEOPLE, equipment=equipment,
        versions=versions, chunks=chunks,
        communications=sorted(comms, key=lambda c: c.date),
        authority=AuthorityMatrix(scopes=SCOPES, authorities=AUTHORITIES),
    )
