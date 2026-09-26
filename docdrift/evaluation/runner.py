"""Run the evaluation set in both governance modes and score it."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..abb_registry import load_chunk_cache
from ..app import build_pipeline
from ..config import Settings
from ..governance import GovernanceMode
from ..models import ContentProvenance
from .questions import EVAL_CASES, EvalCase


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class CaseResult:
    case_id: str
    question: str
    probes: str
    mode: str
    status: str
    answered: bool
    asset: str | None
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _run_case(pipeline, case: EvalCase, mode: GovernanceMode,
              abb_text_indexed: bool = True) -> CaseResult:
    answer, bundle = pipeline.ask(case.question, mode=mode)
    asset = bundle.equipment.equipment.asset_tag if bundle.equipment.equipment else None
    result = CaseResult(case.case_id, case.question, case.probes, mode.value,
                        answer.status.value, answer.answered, asset)
    add = result.checks.append

    if case.expect_asset is not None:
        add(Check("asset", asset == case.expect_asset,
                  f"expected {case.expect_asset}, got {asset}"))
    else:
        add(Check("asset", asset is None, f"expected no asset, got {asset}"))

    add(Check("answered", answer.answered == case.expect_answered,
              f"expected answered={case.expect_answered}, got {answer.answered}"))

    expected_status = case.expect_status.get(mode.value)
    if expected_status:
        add(Check("status", answer.status.value == expected_status,
                  f"expected {expected_status}, got {answer.status.value}"))

    by_id = {c.communication.comm_id: c for c in bundle.candidate_changes}
    expected_classes = dict(case.expect_classifications)
    expected_classes.update(case.expect_classifications_strict if mode is GovernanceMode.STRICT
                            else case.expect_classifications_flexible)
    for comm_id, expected in expected_classes.items():
        got = by_id[comm_id].classification if comm_id in by_id else "not considered"
        add(Check(f"class:{comm_id}", got == expected, f"expected {expected}, got {got}"))
    for comm_id in case.expect_effective:
        add(Check(f"effective:{comm_id}", comm_id in by_id and by_id[comm_id].effective,
                  "expected to pass every condition"))
    for comm_id in case.expect_not_effective:
        add(Check(f"refused:{comm_id}", comm_id not in by_id or not by_id[comm_id].effective,
                  "expected to be refused"))

    cited = [(c.chunk_id, s) for s in answer.guidance for c in s.citations]
    for doc_id, version in case.forbid_cited_versions:
        bad = [cid for cid, _ in cited
               if (ch := pipeline.store.get_chunk(cid)) and ch.doc_id == doc_id
               and ch.version == version]
        add(Check(f"no-superseded:{doc_id}@{version}", not bad, f"cited {bad}"))

    if case.expect_cited_pages and answer.answered and abb_text_indexed:
        pages = {(ch.doc_id, ch.page) for cid, _ in cited if (ch := pipeline.store.get_chunk(cid))}
        want = set(case.expect_cited_pages)
        add(Check("cited-page", bool(pages & want),
                  f"expected one of {sorted(want)}, cited {sorted(pages)[:4]}"))

    if case.require_abb_provenance and answer.answered and abb_text_indexed:
        provs = {c.provenance for s in answer.guidance for c in s.citations}
        add(Check("provenance", ContentProvenance.ABB_PUBLIC_PDF in provs,
                  f"expected at least one ABB-sourced citation, got {sorted(p.value for p in provs)}"))

    if case.expect_answered:
        add(Check("gates", all(g.passed for g in answer.gates),
                  "; ".join(g.gate for g in answer.gates if not g.passed) or "all gates passed"))
    else:
        # A withheld answer is the gates working, not the gates failing.
        add(Check("withheld", not answer.answered and bool(answer.clarification_needed),
                  "expected the answer to be withheld with an explanation"))
    return result


def run_evaluation(cases: list[EvalCase] | None = None,
                   settings: Settings | None = None) -> list[CaseResult]:
    cases = cases or EVAL_CASES
    settings = settings or Settings()
    pipeline = build_pipeline(settings)
    indexed = bool(load_chunk_cache())
    return [_run_case(pipeline, case, mode, abb_text_indexed=indexed)
            for case in cases
            for mode in (GovernanceMode.STRICT, GovernanceMode.FLEXIBLE)]
