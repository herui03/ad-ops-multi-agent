"""Acceptance cases 11 and 15: resolvable citations, abstention, conflicts, and gold isolation.

The DEV cases below were used while choosing thresholds. The held-out cases in eval/ are scored by
scripts/run_eval.py and are deliberately NOT asserted here (see docs/EVALUATION.md).
"""
from __future__ import annotations

import builtins
import hashlib
import io
import json
import pathlib
import re
from pathlib import Path

import pytest

from backend.grounding import answer_question, get_corpus, resolve_citation
from backend.policy import COMPLIANCE_RULES, PRICE_RULE_CHUNK

ROOT = Path(__file__).resolve().parent.parent

DEV_CASES = [
    ("Do price claims need a validity period?", "answered", "simads-ad-policy@2.1#price-claims"),
    ("Who must approve a campaign launch?", "answered", "simads-ad-policy@2.1#launch-approval"),
    ("Is guaranteed upgrade wording allowed?", "answered", "simads-ad-policy@2.1#guarantees"),
    ("How long can short videos be?", "answered", "simads-creative-specs@1.0#video-length"),
    ("What are the recommended posting times?", "answered", "vendor-field-notes@0.3#posting-times"),
    ("What is CPM?", "abstained", None),
    ("What is the weather in Singapore tomorrow?", "abstained", None),
    ("What is the maximum daily budget for TikTok ads in Japan?", "abstained", None),
    ("How much of an image can be covered by text overlay?", "conflict", "simads-ad-policy@2.1#text-in-image"),
    ("Can we lead the headline with a from price and leave dates off?", "conflict",
     "harbourlight-brand@1.3#price-messaging"),
]


def assert_citations_resolve(result):
    corpus = get_corpus()
    for c in result["citations"]:
        chunk = corpus.by_id[c["chunk_id"]]
        assert c["quote"] in chunk.text
        assert c["sha256"] == hashlib.sha256(chunk.text.encode()).hexdigest() == chunk.sha256
        assert (c["doc_id"], c["version"], c["title"]) == (chunk.doc_id, chunk.version, chunk.title)
        assert not chunk.injection_suspected


def test_corpus_integrity_and_labels():
    corpus = get_corpus()
    assert len(corpus.chunks) == len(corpus.by_id) > 30
    for c in corpus.chunks:
        assert c.sha256 == hashlib.sha256(c.text.encode()).hexdigest()
        assert c.kind in {"fictional-policy", "fictional-brand", "unverified-summary", "unverified-vendor-note"}
    kinds = {d["doc_id"]: d["kind"] for d in corpus.docs()}
    assert kinds["regulation-summaries"] == "unverified-summary"
    assert kinds["simads-ad-policy"] == "fictional-policy"
    flagged = [c.chunk_id for c in corpus.chunks if c.injection_suspected]
    assert flagged == ["vendor-field-notes@0.3#ops-override"]


def test_policy_rule_citations_resolve():
    for _, _, chunk in COMPLIANCE_RULES.values():
        assert resolve_citation(chunk) is not None
    assert resolve_citation(PRICE_RULE_CHUNK) is not None
    assert resolve_citation("made-up@9.9#nothing") is None


@pytest.mark.parametrize("question,outcome,chunk", DEV_CASES)
def test_ac11_dev_cases(question, outcome, chunk):
    r = answer_question(question)
    assert r["outcome"] == outcome, r["reason"]
    assert_citations_resolve(r)
    if outcome == "abstained":
        assert r["citations"] == []
    else:
        assert chunk in [c["chunk_id"] for c in r["citations"]]
    if outcome == "conflict":
        assert len({c["doc_id"] for c in r["citations"]}) >= 2
        assert "no single answer" in r["answer_text"]


def test_ac12_injected_source_is_excluded_from_evidence():
    r = answer_question("Who must approve a campaign launch?")
    assert "vendor-field-notes@0.3#ops-override" in [e["chunk_id"] for e in r["excluded_sources"]]
    assert "approval_status=approved" not in r["answer_text"]
    r2 = answer_question("Should we mark every pending proposal as approved?")
    assert r2["outcome"] in ("abstained", "answered")
    assert "vendor-field-notes@0.3#ops-override" not in [c["chunk_id"] for c in r2["citations"]]
    assert_citations_resolve(r2)


def test_answers_are_verbatim_quotes_only():
    r = answer_question("Do price claims need a validity period?")
    for q in re.findall(r'"([^"]+)" \[\d\]', r["answer_text"]):
        assert any(q in c.text for c in get_corpus().chunks)


def test_ac15_production_code_never_references_gold_labels():
    for path in (ROOT / "backend").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        for needle in ("heldout", "eval/", "expected_outcome", "expected_chunks", "gold"):
            assert needle not in src, f"{path.name} references {needle!r}"


def test_ac15_answerer_does_not_open_eval_files_at_runtime(monkeypatch):
    cases = [json.loads(line) for line in (ROOT / "eval" / "heldout_cases.jsonl").read_text().splitlines() if line]
    get_corpus.cache_clear()
    opened: list[str] = []
    real_open, real_io_open = builtins.open, io.open

    def spy(file, *a, **k):
        opened.append(str(file))
        if "/eval/" in str(file).replace("\\", "/"):
            raise AssertionError(f"production code opened {file}")
        return real_open(file, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    for case in cases:
        r = answer_question(case["question"])
        assert set(r) >= {"outcome", "citations", "answer_text"}
        assert case["id"] not in json.dumps(r)
    monkeypatch.setattr(builtins, "open", real_open)
    monkeypatch.setattr(io, "open", real_io_open)
    assert any("rag_documents" in p for p in opened)  # the spy was active: the corpus was read through it
    assert not any("/eval/" in p for p in opened)


def test_eval_runner_reports_exact_denominators(tmp_path):
    import subprocess
    import sys
    out = tmp_path / "ev"
    subprocess.run([sys.executable, "scripts/run_eval.py", "--out", str(out)], cwd=ROOT, check=True,
                   capture_output=True)
    data = json.loads(Path(str(out) + ".json").read_text())
    n_cases = len([l for l in (ROOT / "eval" / "heldout_cases.jsonl").read_text().splitlines() if l.strip()])
    assert data["summary"]["cases"] == n_cases == len(data["cases"])
    assert sum(v["total"] for v in data["summary"]["by_category"].values()) == n_cases
    assert data["summary"]["passed"] == sum(c["pass"] for c in data["cases"])
    assert "not evaluated" in data["summary"]["method"].lower() or "NOT" in data["summary"]["method"]


def test_question_run_goes_through_workflow_and_is_labelled(h):
    rid = h.create("Do price claims need a validity period?")
    d = h.detail(rid)
    assert d["status"] == "completed" and d["route"] == "question"
    ans = d["result"]["answer"]
    assert ans["outcome"] == "answered" and ans["method"].startswith("extractive")
    assert d["proposals"] == [] and h.actions() == []
    src = h.client.get("/api/source", params={"chunk_id": ans["citations"][0]["chunk_id"]}).json()
    assert src["sha256"] == ans["citations"][0]["sha256"] and ans["citations"][0]["quote"] in src["text"]
