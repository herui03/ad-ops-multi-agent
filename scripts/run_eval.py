"""Held-out grounding evaluation (retrieval + provenance, no language model).

The runner owns the gold labels. The production answerer (backend.grounding.answer_question)
receives only the question string. It never sees case ids, categories or expected outputs, and it
never opens eval/ (tests/test_grounding.py enforces both).

Per case it checks:
  * outcome is one of the allowed outcomes (answered / abstained / conflict)
  * every citation resolves: chunk exists, quote is a verbatim substring, sha256 matches the chunk
  * expected chunks are cited (any-of, or all-of for conflict cases)
  * forbidden chunks are not cited and forbidden text does not appear in the answer

Usage: python scripts/run_eval.py [--out docs/evidence/eval-heldout] [--cases eval/heldout_cases.jsonl]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.grounding import answer_question, get_corpus  # noqa: E402


def check_case(case: dict, result: dict) -> list[str]:
    corpus = get_corpus()
    failures = []
    # The case files predate review round 5 and say "answered"; the answerer now reports that state as
    # "unverified_excerpts" (same behaviour, honest label). The case files are left unedited.
    expected = ["unverified_excerpts" if o == "answered" else o for o in case["expected_outcome"]]
    case = {**case, "expected_outcome": expected}
    if result["outcome"] not in case["expected_outcome"]:
        failures.append(f"outcome {result['outcome']!r} not in {case['expected_outcome']}")
    cited = [c["chunk_id"] for c in result["citations"]]
    candidates = [c["chunk_id"] for c in result.get("candidate_evidence", [])]
    if result["outcome"] != "abstained" and candidates:
        failures.append("candidate evidence attached to a non-abstained outcome")
    for c in result["citations"] + result.get("candidate_evidence", []):
        chunk = corpus.by_id.get(c["chunk_id"])
        if chunk is None:
            failures.append(f"citation {c['chunk_id']} does not resolve")
            continue
        if c["quote"] not in chunk.text:
            failures.append(f"quote for {c['chunk_id']} is not verbatim")
        if c["sha256"] != hashlib.sha256(chunk.text.encode()).hexdigest():
            failures.append(f"sha256 mismatch for {c['chunk_id']}")
    expected = case.get("expected_chunks")
    if expected and result["outcome"] in ("unverified_excerpts", "conflict"):
        if case.get("require_all_expected"):
            missing = [e for e in expected if e not in cited]
            if missing:
                failures.append(f"missing expected citations {missing}")
        elif not set(expected) & set(cited):
            failures.append(f"none of expected citations {expected} cited (got {cited})")
    for f in case.get("forbidden_chunks", []):
        if f in cited or f in candidates:
            failures.append(f"cited forbidden chunk {f}")
    for t in case.get("forbidden_text", []):
        if t.lower() in result["answer_text"].lower():
            failures.append(f"answer contains forbidden text {t!r}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="eval/heldout_cases.jsonl")
    ap.add_argument("--out", default="docs/evidence/eval-heldout")
    ap.add_argument("--label", default="held-out", help="how to describe this case set in the report "
                    "(e.g. 'held-out' or 'regression')")
    args = ap.parse_args()
    with open(args.cases, encoding="utf-8") as fh:
        cases = [json.loads(line) for line in fh if line.strip()]
    rows, by_cat = [], defaultdict(lambda: [0, 0])
    for case in cases:
        result = answer_question(case["question"])  # question only
        failures = check_case(case, result)
        by_cat[case["category"]][1] += 1
        by_cat[case["category"]][0] += not failures
        rows.append({"id": case["id"], "category": case["category"], "question": case["question"],
                     "outcome": result["outcome"], "reason": result["reason"],
                     "cited": [c["chunk_id"] for c in result["citations"]],
                     "excluded": [e["chunk_id"] for e in result["excluded_sources"]],
                     "pass": not failures, "failures": failures})
    total_pass = sum(r["pass"] for r in rows)
    answerer = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "grounding.py")
    with open(answerer, "rb") as fh:
        answerer_sha = hashlib.sha256(fh.read()).hexdigest()
    summary = {"label": args.label, "cases_file": args.cases, "answerer_sha256": answerer_sha, "cases": len(rows), "passed": total_pass,
               "by_category": {k: {"passed": v[0], "total": v[1]} for k, v in sorted(by_cat.items())},
               "method": "extractive TF-IDF answerer, no language model; live LLM quality NOT evaluated here"}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out + ".json", "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "cases": rows}, fh, indent=2)
    lines = ["| id | category | outcome | pass | cited / notes |", "|---|---|---|---|---|"]
    for r in rows:
        note = ", ".join(r["cited"]) or "-"
        if r["failures"]:
            note += " — FAIL: " + "; ".join(r["failures"])
        lines.append(f"| {r['id']} | {r['category']} | {r['outcome']} | {'yes' if r['pass'] else 'NO'} | {note} |")
    cat = "; ".join(f"{k} {v['passed']}/{v['total']}" for k, v in summary["by_category"].items())
    md = f"**{total_pass}/{len(rows)} {args.label} cases passed** ({cat}). Cases: `{args.cases}`. Answerer `backend/grounding.py` sha256 `{answerer_sha}`.\n\n" + "\n".join(lines) + "\n"
    with open(args.out + ".md", "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
