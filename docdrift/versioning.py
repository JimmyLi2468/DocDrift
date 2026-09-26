"""Stage 3 - version resolution and the freshness search date.

The freshness date is the effective date of version n-1, not of the current
version: a change approved between n-1 and n may have been approved but never
carried into n, and searching only from n's date would miss it.
"""
from __future__ import annotations

from datetime import date

from .models import DocumentVersion, Equipment, VersionResolution


def resolve_versions(store, equipment: Equipment) -> list[VersionResolution]:
    out: list[VersionResolution] = []
    for doc_id in equipment.doc_ids:
        # The asset register is authoritative about which documents apply to an asset.
        # Model/family metadata extracted from the document is a cross-check, not the
        # filter: a catalogue that never spells out a model number in its first pages
        # is still the manual the plant has assigned to that machine.
        applicable = store.versions_for_doc(doc_id)
        if not applicable:
            continue
        current = next((v for v in applicable if v.status == "current"), None)
        if current is None:
            continue
        previous: DocumentVersion | None = None
        if current.supersedes:
            previous = next((v for v in applicable if v.version == current.supersedes), None)
        if previous is None:
            older = [v for v in applicable if v.effective_date < current.effective_date]
            previous = max(older, key=lambda v: v.effective_date) if older else None
        freshness_from: date = previous.effective_date if previous else current.effective_date
        out.append(VersionResolution(doc_id=doc_id, title=current.title, current=current,
                                     previous=previous, freshness_search_from=freshness_from))
    return out
