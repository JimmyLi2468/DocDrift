"""Render the watermarked synthetic n-1 documents.

    PYTHONPATH=. python scripts/make_synthetic_history.py
"""
from __future__ import annotations

import sys

from docdrift.synthetic_pdf import render_all


def main() -> int:
    try:
        paths = render_all()
    except ImportError:
        print("reportlab is required: pip install reportlab", file=sys.stderr)
        return 2
    for p in paths:
        print(f"  wrote {p.name}")
    print(f"{len(paths)} watermarked synthetic historical documents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
