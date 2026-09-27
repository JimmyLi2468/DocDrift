"""Local LLM adapter.

The default backend is extractive: the answer is assembled from retrieved sentences
verbatim, so every citation is exact by construction and the deterministic gates can
verify it. The Ollama backend is used only to *rephrase* already-grounded sentences;
it is never allowed to introduce content, and its output is re-validated downstream.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Protocol


class LLMClient(Protocol):
    name: str
    def available(self) -> bool: ...
    def rephrase(self, sentence: str) -> str: ...


class ExtractiveClient:
    name = "extractive"

    def available(self) -> bool:
        return True

    def rephrase(self, sentence: str) -> str:
        return sentence


class OllamaClient:
    name = "ollama"

    def __init__(self, model: str, url: str, timeout: float = 30.0) -> None:
        self.model, self.url, self.timeout = model, url, timeout

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=2.0):
                return True
        except Exception:
            return False

    def rephrase(self, sentence: str) -> str:
        prompt = (
            "Rewrite the maintenance instruction below as one short imperative sentence for a plant "
            "operator. Keep every number, unit, parameter, terminal and fault code exactly as written. "
            "Do not add, remove or infer any technical fact, value or component name. "
            "Reply with the sentence only.\n\n"
            f"{sentence}"
        )
        payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False, "keep_alive": "30m",
                              "options": {"temperature": 0.0, "seed": 7, "num_predict": 160}}).encode()
        req = urllib.request.Request(f"{self.url}/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())["response"].strip()
        except Exception:
            return sentence


_TOKEN = re.compile(r"\b\d+(?:[.,]\d+)*\b|\b[A-Z]{1,5}\d[\w.\-]*\b|\b\d+[A-Za-z]+\b")
_NEGATION = re.compile(r"\b(not|never|no|don't|do not|must not|avoid|without)\b", re.I)


def faithful(original: str, rewritten: str) -> tuple[bool, str]:
    """Accept a model's rewording only if it cannot have changed the instruction:
    every number, code and unit-bearing value in the rewrite appears in the original,
    none of the original's values is dropped, no negation appears or disappears, and
    the rewrite is not much longer than what it rewords."""
    a, b = set(_TOKEN.findall(original)), set(_TOKEN.findall(rewritten))
    if b - a:
        return False, f"introduced {sorted(b - a)}"
    if a - b:
        return False, f"dropped {sorted(a - b)}"
    if bool(_NEGATION.search(original)) != bool(_NEGATION.search(rewritten)):
        return False, "negation added or removed"
    if len(rewritten) > 1.5 * len(original) + 20 or not rewritten.strip():
        return False, "length out of bounds"
    return True, "values preserved"


class GuardedClient:
    """Wraps a model client: a rewording that fails `faithful` is discarded and the
    manual's own sentence is used. The number of discarded rewordings is kept for the
    evidence panel and the tests."""

    def __init__(self, inner) -> None:
        self.inner, self.name = inner, inner.name
        self.rejected: list[tuple[str, str]] = []

    def available(self) -> bool:
        return self.inner.available()

    def rephrase(self, sentence: str) -> str:
        out = self.inner.rephrase(sentence)
        if out == sentence:
            return sentence
        ok, why = faithful(sentence, out)
        if not ok:
            self.rejected.append((out, why))
            return sentence
        return out


def build_llm(settings) -> LLMClient:
    if settings.llm_backend == "ollama":
        client = OllamaClient(settings.ollama_model, settings.ollama_url)
        if client.available():
            return GuardedClient(client)
        import logging
        logging.getLogger("docdrift").warning(
            "Ollama not reachable at %s; answers use the manual's own sentences", settings.ollama_url)
    return ExtractiveClient()
