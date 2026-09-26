"""Stage 1 - which machine is the operator actually talking about?

Deterministic extraction (asset tags, model strings, fault codes) resolved against
the asset registry, with an explicit confidence score and an ambiguity check. A low
score stops the pipeline and returns a clarification request instead of an answer.
"""
from __future__ import annotations

import re

from .config import Thresholds
from .models import Equipment, EquipmentMatch

TAG_RE = re.compile(r"\b([A-Z]{1,3}-?\d{1,3})\b")
FAULT_RE = re.compile(r"(?:fault|code|alarm|trip|f)\s*#?\s*(\d{3,5})", re.I)
MODEL_RE = re.compile(r"\b(ACS\d{3}(?:-\d{2})?|ACQ\d{3}|PSTX\d+|PSR\d+|PSE\d+"
                      r"|MS1\d{2}(?:-[\d.]+[A-Z]*)?|MS4\d{2}|AF\d{2,4}|UMC\d+)\b", re.I)


def extract_fault_codes(text: str) -> list[str]:
    return sorted(set(FAULT_RE.findall(text)))


def resolve_equipment(question: str, registry: list[Equipment], th: Thresholds) -> EquipmentMatch:
    tags = [t.replace("-", "") for t in TAG_RE.findall(question)]
    models = [m.upper() for m in MODEL_RE.findall(question)]
    faults = extract_fault_codes(question)

    model_counts: dict[str, int] = {}
    for eq in registry:
        model_counts[eq.model.upper()] = model_counts.get(eq.model.upper(), 0) + 1

    scored: list[tuple[float, Equipment, list[str]]] = []
    for eq in registry:
        score, ev = 0.0, []
        if eq.asset_tag.replace("-", "").upper() in [t.upper() for t in tags]:
            score += 0.60
            ev.append(f"asset tag {eq.asset_tag} found in the asset registry")
        for m in models:
            if m == eq.model.upper():
                score += 0.30
                ev.append(f"model {eq.model} named in the question")
                if model_counts[eq.model.upper()] == 1:
                    # exactly one asset in the register carries this type code
                    score += 0.30
                    ev.append(f"{eq.model} is fitted to only one registered asset "
                              f"({eq.asset_tag})")
            elif eq.family.upper().startswith(m) or m.startswith(eq.family.upper()):
                score += 0.15
                ev.append(f"product family {eq.family} named in the question")
        if score > 0 and faults:
            score += 0.10
            ev.append(f"fault code(s) {', '.join(faults)} parsed from the question")
        if score > 0:
            scored.append((min(score, 0.99), eq, ev))

    scored.sort(key=lambda t: -t[0])
    if not scored:
        return EquipmentMatch(equipment=None, confidence=0.0, asked_tags=tags, fault_codes=faults,
                              evidence=["no asset tag or model in the question matched the registry"])

    best_score, best_eq, ev = scored[0]
    alts = [e.asset_tag for s, e, _ in scored[1:] if best_score - s <= th.equipment_ambiguity_margin]
    if alts:
        best_score *= 0.8
        ev.append(f"ambiguous against {', '.join(alts)}")
    return EquipmentMatch(equipment=best_eq, confidence=round(best_score, 3), evidence=ev,
                          alternatives=alts, asked_tags=tags, fault_codes=faults)
