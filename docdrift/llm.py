"""Local LLM adapter.

The default backend is extractive: the answer is assembled from retrieved sentences
verbatim, so every citation is exact by construction and the deterministic gates can
verify it. The Ollama backend is used only to *rephrase* already-grounded sentences;
it is never allowed to introduce content, and its output is re-validated downstream.
"""
from __future__ import annotations

import json
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
            "operator. Do not add, remove or infer any technical fact, value or component name.\n\n"
            f"{sentence}"
        )
        payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False,
                              "options": {"temperature": 0.0}}).encode()
        req = urllib.request.Request(f"{self.url}/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())["response"].strip()
        except Exception:
            return sentence


def build_llm(settings) -> LLMClient:
    if settings.llm_backend == "ollama":
        client = OllamaClient(settings.ollama_model, settings.ollama_url)
        if client.available():
            return client
    return ExtractiveClient()
