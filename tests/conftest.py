import os

# The tests describe the base stack. A shell that still has production settings
# exported (DOCDRIFT_STACK=production, ...) must not change what they test.
for _k in [k for k in os.environ if k.startswith("DOCDRIFT_")]:
    del os.environ[_k]

import pytest

from docdrift.app import build_pipeline
from docdrift.config import Settings
from docdrift.corpus import build_corpus


@pytest.fixture(scope="session")
def corpus():
    return build_corpus()


@pytest.fixture(scope="session")
def pipeline(tmp_path_factory, corpus):
    s = Settings()
    d = tmp_path_factory.mktemp("audit")
    s.audit_enabled = True                      # the audit tests need it; default is off
    s.audit_path = str(d / "decisions.jsonl")
    s.audit_store_url = f"sqlite:///{d / 'conversations.sqlite'}"
    return build_pipeline(s, corpus)
