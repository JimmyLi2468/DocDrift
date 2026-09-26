"""Run the evaluation set and write a scorecard.

    PYTHONPATH=. python scripts/evaluate.py [--out evaluation_scorecard.md] [--csv evaluation_results.csv]
"""
from __future__ import annotations

import argparse
import csv
import sys
import tempfile

from docdrift.abb_registry import load_chunk_cache
from docdrift.config import Settings
from docdrift.evaluation import run_evaluation

NO_ABB_TEXT = (
    "ABB document text is not indexed on this machine, so no answer can be grounded and "
    "most cases will report Insufficient Evidence. Unpack the library into data/library/, then run "
    "`python scripts/import_library.py` and `python scripts/ingest_abb.py` for a meaningful score."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evaluation_scorecard.md")
    ap.add_argument("--csv", default="evaluation_results.csv")
    args = ap.parse_args()

    settings = Settings()
    settings.audit_path = tempfile.mkstemp(suffix=".jsonl")[1]
    indexed = bool(load_chunk_cache())
    results = run_evaluation(settings=settings)

    passed = sum(1 for r in results if r.passed)
    checks = [c for r in results for c in r.checks]
    lines = [
        "# DocDrift evaluation scorecard", "",
        f"{passed}/{len(results)} case runs passed "
        f"({sum(1 for c in checks if c.passed)}/{len(checks)} individual checks). "
        f"Each case is run twice, once per governance mode.", "",
    ] + ([] if indexed else [f"> **{NO_ABB_TEXT}**", ""]) + [
        "| case | mode | asset | status | result | probes |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.case_id} | {r.mode} | {r.asset or '-'} | {r.status} | "
                     f"{'pass' if r.passed else 'FAIL'} | {r.probes} |")

    failures = [(r, c) for r in results for c in r.checks if not c.passed]
    if failures:
        lines += ["", "## Failed checks", "", "| case | mode | check | detail |", "|---|---|---|---|"]
        lines += [f"| {r.case_id} | {r.mode} | {c.name} | {c.detail} |" for r, c in failures]

    lines += ["", "## Questions", ""]
    seen = set()
    for r in results:
        if r.case_id in seen:
            continue
        seen.add(r.case_id)
        lines.append(f"- **{r.case_id}** {r.question}")

    with open(args.out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(args.csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "mode", "asset", "status", "answered", "check", "passed", "detail"])
        for r in results:
            for c in r.checks:
                w.writerow([r.case_id, r.mode, r.asset, r.status, r.answered,
                            c.name, c.passed, c.detail])

    if not indexed:
        print(NO_ABB_TEXT)
    print(f"{passed}/{len(results)} case runs passed; wrote {args.out} and {args.csv}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
