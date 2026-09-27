"""Stage 2b - precision rerank over the hybrid-retrieval candidates.

Reciprocal rank fusion is good at recall and poor at telling apart two pages that
both contain the right words. In a 600-page firmware manual the fault code appears
in the fault table, in the index, in the parameter listing and in the event-word
tables; in a 1,000-page catalogue every contactor family has a "tightening torque"
row. The rerank uses the three signals that separate them, all deterministic:

  - coverage: the share of the question's content terms present on the page
  - phrase match: adjacent question terms that occur as the same phrase on the page
    ("regular maintenance", "EOL trip class") - headings are phrased that way
  - asset anchoring: the page names the asset's own model or type code, or a series
    range that numerically contains it; naming only the family counts for less
  - heading anchoring: the model is named in the first lines of the page
  - contents pages ("2.1.1 Regular maintenance 10 ...") are demoted: they repeat
    every heading and answer nothing
  - fault definition: the quoted fault code is followed by its explanation
    ("Check ...", "Cause", "What to do") rather than by a page cross-reference
"""
from __future__ import annotations

import re

from .embeddings import tokenize
from .models import Equipment, RetrievedChunk

STOP = set("the a an of to in for and or is are be on at with from that this it if as by what how "
           "do does should which when why can my our after".split())
_XREF = re.compile(r"\(page \d+\)|\(p\. ?\d+\)|\bpage \d+\b", re.I)
_TOC_LINE = re.compile(r"\b\d+(?:\.\d+){1,3}\s+[A-Z][^.\d]{3,70}?\s\d{1,3}\b")
_ACCESSORY = re.compile(r"\b(accessor(?:y|ies)|additional terminal|terminal blocks?|interlock|"
                        r"auxiliary contact blocks?|covers?|spare parts?)\b", re.I)
_EXPLAIN = re.compile(r"\b(check|cause|what to do|make sure|verify|replace|measure)\b", re.I)


def _fold(text: str) -> set[str]:
    from .drift import _stems
    return _stems(text)


def model_patterns(eq: Equipment | None) -> list[re.Pattern]:
    if eq is None:
        return []
    names = {eq.model}
    if eq.type_code:
        names.add(eq.type_code)
    # A variant suffix makes it a different product: "AF38..K" (push-in spring terminals)
    # and "AF38Z" (special-application coils) are not the asset's AF38.
    return [re.compile(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![0-9A-Z])(?!\.\.[A-Z])") for n in names]


def names_model(text: str, eq: Equipment | None) -> bool:
    """The page names this exact model, directly or inside a series range that
    contains it ("PSTX30...370" names PSTX142; "AF40...AF96" does not name AF38)."""
    if eq is None:
        return False
    if any(p.search(text) for p in model_patterns(eq)):
        return True
    base = re.match(r"^([A-Z]+)(\d+)", eq.model)
    if not base:
        return False
    prefix, n = base.group(1), int(base.group(2))
    rng = re.compile(r"(?<![A-Za-z])" + re.escape(prefix) + r"(\d+)\s?(?:\.\.\.|…)\s?"
                     + "(?:" + re.escape(prefix) + r")?(\d+)")
    return any(int(a) <= n <= int(b) for a, b in rng.findall(text))


def names_family(text: str, eq: Equipment | None) -> bool:
    return bool(eq and re.search(r"(?<![A-Za-z])" + re.escape(eq.family) + r"(?![a-z])", text))


def fault_definition(text: str, code: str) -> bool:
    for m in re.finditer(r"(?<![0-9A-F])" + re.escape(code) + r"(?![0-9A-F])", text):
        tail = text[m.end(): m.end() + 420]
        head = tail[:60]
        if _XREF.search(head):                   # "5091 Safe torque off (page 558)"
            continue
        if _EXPLAIN.search(tail):
            return True
    return False


def rerank(hits: list[RetrievedChunk], question: str, equipment: Equipment | None,
           fault_codes: list[str], top_k: int) -> list[RetrievedChunk]:
    if not hits:
        return hits
    from .drift import GENERIC_TOPIC_TERMS
    asset_words = _fold(" ".join(filter(None, [equipment.asset_tag if equipment else None])))
    terms = ({t for t in _fold(question) if t not in STOP and len(t) > 2}
             - asset_words - GENERIC_TOPIC_TERMS)
    best_fused = max(h.score for h in hits) or 1.0
    ordered = [t for t in re.findall(r"[a-z0-9]+", question.lower())
               if t not in STOP and len(t) > 1]
    bigrams = [f"{a} {b}" for a, b in zip(ordered, ordered[1:])]

    scored = []
    for h in hits:
        text = h.chunk.text
        words = _fold(text)
        coverage = len(terms & words) / max(len(terms), 1)
        anchor = 0.6 if names_model(text, equipment) else (0.25 if names_family(text, equipment) else 0.0)
        low = " ".join(re.findall(r"[a-z0-9]+", text.lower()))
        phrases = sum(1 for bg in bigrams if bg in low)
        # The model named in the page heading means the page is about that model, not
        # merely a mention of it in an accessory or compatibility table.
        if anchor and names_model(text[:220], equipment):
            anchor += 0.3
        toc = len(_TOC_LINE.findall(text)) >= 6
        if _ACCESSORY.search(text[:160]):        # a page about an accessory for the model
            anchor -= 0.3
        s = (coverage + min(1.0, 0.5 * phrases) + anchor - (0.8 if toc else 0.0)
             + 0.25 * (h.score / best_fused))
        if fault_codes:
            if any(fault_definition(text, f) for f in fault_codes):
                s += 1.0
            elif any(f in text for f in fault_codes):
                s += 0.2
            xrefs = len(_XREF.findall(text))
            s -= min(0.4, 0.02 * xrefs)          # index and cross-reference pages
        scored.append((s, h))
    scored.sort(key=lambda p: -p[0])
    return [h.model_copy(update={"score": round(s, 4)}) for s, h in scored[:top_k]]
