"""Console demo.

    PYTHONPATH=. python -m docdrift.cli "What regular maintenance does the manual specify for softstarter S2?"
    PYTHONPATH=. python -m docdrift.cli --mode flexible "..."
"""
from __future__ import annotations

import argparse
import textwrap

from .app import build_pipeline
from .config import Settings
from .governance import GovernanceMode

DEFAULT_Q = "Drive M4 trips with fault 5091 after operating for ten minutes."
W = 96


def render(answer) -> str:
    L = ["=" * W, f"QUESTION   {answer.question}", "=" * W,
         f"EQUIPMENT  {answer.equipment_summary}",
         f"CONFIDENCE {answer.equipment_confidence:.2f}",
         f"MODE       {answer.mode.value}",
         f"STATUS     {answer.status.value}", ""]
    if answer.clarification_needed:
        L += ["CLARIFICATION NEEDED",
              textwrap.fill(answer.clarification_needed, W, initial_indent="  ",
                            subsequent_indent="  "), ""]
    if answer.guidance:
        L.append("GUIDANCE FROM THE CURRENT DOCUMENTATION")
        for i, s in enumerate(answer.guidance, 1):
            L.append(textwrap.fill(f"{i}. {s.text}", W, initial_indent="  ",
                                   subsequent_indent="     "))
            for c in s.citations:
                L.append(f"       [{c.label}]")
        L.append("")
    if answer.applicable_documents:
        L += ["APPLICABLE DOCUMENTS"] + [f"  - {d}" for d in answer.applicable_documents] + [""]
    if answer.pending_change:
        L += ["POTENTIAL APPROVED UPDATE NOT YET IN THE DOCUMENT",
              textwrap.fill(answer.pending_change, W, initial_indent="  ",
                            subsequent_indent="  "), "", "APPROVAL EVIDENCE"]
        L += [textwrap.fill(e, W, initial_indent="  - ", subsequent_indent="    ")
              for e in answer.approval_evidence] + [""]
    if answer.other_open_changes:
        L += ["OTHER APPROVED CHANGES OPEN AGAINST THIS ASSET"]
        L += [textwrap.fill(e, W, initial_indent="  - ", subsequent_indent="    ")
              for e in answer.other_open_changes] + [""]
    if answer.escalation:
        L += ["ESCALATION", textwrap.fill(answer.escalation, W, initial_indent="  ",
                                          subsequent_indent="  "), ""]
    if answer.evidence_considered:
        L.append("EVIDENCE CONSIDERED")
        for d in answer.evidence_considered:
            flag = "USED" if not d.failed_conditions else "REFUSED"
            L.append(f"  [{flag:7s}] {d.comm_id:15s} {d.channel.value:22s} "
                     f"{d.decision_state.value:21s} {d.authority_state.value:15s} {d.classification}")
            for reason in d.detail[:2]:
                L.append(textwrap.fill(reason, W, initial_indent="              ",
                                       subsequent_indent="                "))
        L.append("")
    L.append("VERIFICATION GATES")
    L += [f"  [{'PASS' if g.passed else 'FAIL'}] {g.gate}: {g.detail}" for g in answer.gates]
    L += ["", textwrap.fill(answer.disclaimer, W), "=" * W]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*", default=None)
    ap.add_argument("--mode", choices=[m.value for m in GovernanceMode], default=None)
    args = ap.parse_args()

    settings = Settings.from_env()
    if args.mode:
        settings.governance_mode = GovernanceMode(args.mode)
    pipeline = build_pipeline(settings)
    answer, _ = pipeline.ask(" ".join(args.question) or DEFAULT_Q)
    print(render(answer))


if __name__ == "__main__":
    main()
