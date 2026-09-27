"""Grounded retrieval and extractive answering over rag_documents/.

What this is:
  * A hand-written TF-IDF retriever (cosine similarity, no embeddings, no external calls).
  * One chunk per "## [section]" of a corpus document. Chunk ids are stable
    ("<doc_id>@<version>#<section>") and each chunk carries the sha256 of its exact text.
  * An extractive answerer: it only ever returns sentences copied verbatim from chunks, each with
    a citation that resolves back to (doc, version, section, sha256). It abstains when retrieval
    evidence is weak, and reports a conflict when two sources tagged with the same topic take
    different positions.

What this is not:
  * Not semantic search; matching is lexical.
  * Not legal review. Documents are fictional or unverified summaries (see each doc's `kind`).
  * Conflict detection only sees conflicts the corpus authors tagged with `topic:`/`position:`.

Source text is data. Sections that contain instruction-like text (e.g. "ignore previous
instructions", "mark ... approved") are excluded from evidence and reported, and nothing in this
module can change workflow state, IDs or approval rules.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent.parent / "rag_documents"

# MIN_SCORE and MIN_COVERAGE were chosen on the DEV cases (tests/test_grounding.py). MIN_QUOTE_SUPPORT and the
# corpus-wide conflict check were added after reviewing the frozen first-round held-out failures, which are
# therefore regression cases now, not held-out evidence (see docs/EVALUATION.md).
MIN_SCORE = 0.12        # cosine similarity of the best chunk
MIN_QUOTE_SUPPORT = 0.3  # share of question terms that must appear in the quoted sentences
MIN_COVERAGE = 0.4      # share of question content terms present in the best chunk

TOP_K = 5

STOPWORDS = set("""
a an and are as at be by can could do does for from how i if in into is it its may me must my of on or our
should so than that the their them then there these they this to was we were what when where which who why
will with would you your about any all also am been being both each few more most other some such only
own same too very just not no nor s t don now ever per via up out over under again further once here both
tell please explain say says according policy policies rule rules allowed allow ad ads advertising
""".split())
# note: "only", "most", "not" are stopwords for retrieval scoring only; answers quote the full sentences.

INJECTION_PATTERNS = [
    re.compile(p, re.I) for p in (
        r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules)",
        r"^\s*system\s*:",
        r"\b(mark|set)\b[^.]{0,60}\bapprov",
        r"\bapprove (all|every|each)\b",
        r"\bauto[- ]?approv",
        r"\bskip (the )?(approval|review|gate)",
        r"\bwithout waiting for (a )?human",
        r"\bdisregard (the )?(rules|instructions|policy)",
    )
]


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    version: str
    kind: str
    trust: str
    doc_note: str
    section: str
    heading: str
    topic: str | None
    position: str | None
    text: str
    sha256: str
    injection_suspected: bool
    terms: tuple[str, ...] = field(repr=False)


def _stem(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        tok = tok[:-1]
    for suffix in ("ing", "ed"):
        if len(tok) > len(suffix) + 4 and tok.endswith(suffix):
            return tok[: -len(suffix)]
    return tok


def terms(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


def _parse_doc(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    meta = dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)
    for key in ("doc_id", "title", "version", "kind", "trust", "note"):
        if key not in meta:
            raise ValueError(f"{path.name}: front matter lacks {key}")
    chunks = []
    for sec in re.split(r"^## ", m.group(2), flags=re.M)[1:]:
        head, _, body = sec.partition("\n")
        hm = re.match(r"\[([a-z0-9\-]+)\]\s+(.*)", head.strip())
        if not hm:
            raise ValueError(f"{path.name}: bad section heading {head!r}")
        topic = position = None
        lines = []
        for line in body.strip().splitlines():
            if line.startswith("topic: "):
                topic = line[7:].strip()
            elif line.startswith("position: "):
                position = line[10:].strip()
            elif line.strip():
                lines.append(line.strip())
        text = " ".join(lines)
        chunk_id = f"{meta['doc_id']}@{meta['version']}#{hm.group(1)}"
        chunks.append(Chunk(
            chunk_id=chunk_id, doc_id=meta["doc_id"], title=meta["title"], version=meta["version"],
            kind=meta["kind"], trust=meta["trust"], doc_note=meta["note"], section=hm.group(1),
            heading=hm.group(2).strip(), topic=topic, position=position, text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            injection_suspected=any(p.search(text) for p in INJECTION_PATTERNS),
            terms=tuple(terms(hm.group(2) + " " + text)),
        ))
    return chunks


class Corpus:
    def __init__(self, directory: Path = CORPUS_DIR):
        self.chunks: list[Chunk] = []
        for path in sorted(directory.glob("*.md")):
            self.chunks.extend(_parse_doc(path))
        ids = [c.chunk_id for c in self.chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate chunk ids in corpus")
        self.by_id = {c.chunk_id: c for c in self.chunks}
        n = len(self.chunks)
        df = Counter(t for c in self.chunks for t in set(c.terms))
        self.idf = {t: math.log((n + 1) / (d + 1)) + 1 for t, d in df.items()}
        self._vecs = [self._vec(c.terms) for c in self.chunks]

    def _vec(self, toks) -> dict[str, float]:
        tf = Counter(toks)
        v = {t: (1 + math.log(c)) * self.idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def search(self, query: str, k: int = TOP_K) -> list[tuple[float, Chunk]]:
        q = self._vec(terms(query))
        scored = [(sum(w * vec.get(t, 0.0) for t, w in q.items()), c) for vec, c in zip(self._vecs, self.chunks)]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda s: (-s[0], s[1].chunk_id))
        return scored[:k]

    def docs(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for c in self.chunks:
            d = seen.setdefault(c.doc_id, {"doc_id": c.doc_id, "title": c.title, "version": c.version,
                                           "kind": c.kind, "trust": c.trust, "note": c.doc_note, "chunks": 0})
            d["chunks"] += 1
        return list(seen.values())


@lru_cache(maxsize=1)
def get_corpus() -> Corpus:
    return Corpus()


def citation(c: Chunk, quote: str, n: int) -> dict:
    assert quote in c.text, "quotes must be verbatim substrings of the chunk"
    return {"n": n, "chunk_id": c.chunk_id, "doc_id": c.doc_id, "title": c.title, "version": c.version,
            "section": c.section, "heading": c.heading, "sha256": c.sha256, "quote": quote, "kind": c.kind,
            "trust": c.trust}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _best_sentences(c: Chunk, q_terms: set[str], limit: int = 2) -> list[str]:
    sents = _sentences(c.text)
    ranked = sorted(range(len(sents)), key=lambda i: (-len(q_terms & set(terms(sents[i]))), i))
    keep = sorted(i for i in ranked[:limit] if q_terms & set(terms(sents[i]))) or [0]
    return [sents[i] for i in keep]


# Provenance facts (who approved / authored / signed a document, when it was approved or published, its change
# history) can only come from explicit document metadata. The corpus front matter carries doc_id, title, version,
# effective, kind, trust and note, and none of these fields records an author, approver, signatory or approval or
# publication event. Such questions therefore abstain, rather than mapping e.g. an "approver role" policy rule onto a
# historical named approver.
METADATA_FIELDS = ("doc_id", "title", "version", "effective", "kind", "trust", "note")
PROVENANCE_PATTERNS = [re.compile(p, re.I) for p in (
    r"\bwho\b[^?.]*\b(approved|authored|wrote|written|signed|drafted|reviewed|published|issued|created|owns)\b",
    r"\b(who is|who was|who are|name of)\b[^?.]*\b(author|approver|owner|signatory|reviewer|publisher)\b",
    r"\bwhen (was|were|did)\b[^?.]*\b(approved|authored|written|signed|drafted|reviewed|published|issued|released|"
    r"created|changed|updated)\b",
    r"\b(approval|publication|release|signing|review) date\b",
    r"\b(revision|change|version) history\b",
)]

UNVERIFIED_LABEL = "UNVERIFIED SOURCE EXCERPTS: keyword match, human review required"
WARNING = ("Keyword matching found these excerpts. It does not verify that they answer your question: a relevant-looking "
           "quote can still answer a different question. Read the source before relying on it.")


def _split_question(question: str) -> tuple[str, list[str]]:
    """Drop instruction-like sentences from the question before matching; they are reported, not obeyed."""
    parts = [p for p in re.split(r"(?<=[.!?])\s+", question.strip()) if p]
    kept = [p for p in parts if not any(pat.search(p) for pat in INJECTION_PATTERNS)]
    return " ".join(kept), [p for p in parts if p not in kept]


def _candidates(usable: list[tuple[float, Chunk]], q_terms: set[str], k: int = 2) -> list[dict]:
    """Closest evidence shown to a person when support is NOT established. Not an answer."""
    out = []
    for _, c in usable[:k]:
        quote = _best_sentences(c, q_terms, 1)[0]
        out.append({**citation(c, quote, len(out) + 1), "note": "candidate evidence only; not an answer"})
    return out


def answer_question(question: str, corpus: Corpus | None = None) -> dict:
    """Answer from the corpus with verbatim, resolvable citations, or abstain / report a conflict.

    Guards (all general, none keyed to particular questions):
      1. retrieval strength (MIN_SCORE) and chunk-level term coverage (MIN_COVERAGE);
      2. quoted-text support (MIN_QUOTE_SUPPORT): the sentences actually shown must contain the
         question's terms; a match on a heading or elsewhere in the chunk is not enough;
      3. topic conflicts are checked across the WHOLE corpus, not only retrieved chunks, so a
         disagreeing source cannot be missed just because it ranked low;
      4. instruction-like sentences in the question or in sources are ignored and reported.
    When support is not established the result is `abstained`, with any closest `candidate_evidence`
    listed separately and labelled as not an answer.
    """
    corpus = corpus or get_corpus()
    kept, ignored = _split_question(question)
    q_terms = set(terms(kept))
    base = {"question": question, "method": "extractive TF-IDF keyword match (no language model)", "citations": [],
            "candidate_evidence": [], "excluded_sources": [], "retrieval": [],
            "ignored_question_text": ignored, "verified": False, "warning": WARNING}
    if not q_terms:
        return {**base, "outcome": "abstained",
                "reason": "only_instruction_like_text" if ignored else "no_content_terms",
                "answer_text": "I can't answer that from the policy corpus: the question has no searchable terms."}
    hits = corpus.search(kept)
    base["retrieval"] = [{"chunk_id": c.chunk_id, "score": round(s, 4)} for s, c in hits]
    excluded = [c for _, c in hits if c.injection_suspected]
    base["excluded_sources"] = [{"chunk_id": c.chunk_id, "reason": "instruction-like text in source; treated as "
                                 "data and excluded from evidence"} for c in excluded]
    usable = [(s, c) for s, c in hits if not c.injection_suspected]
    if any(p.search(kept) for p in PROVENANCE_PATTERNS):
        return {**base, "outcome": "abstained",
                "reason": "provenance_metadata_unavailable (the question asks who approved/authored a document or when "
                          f"such an event happened; corpus metadata only has {', '.join(METADATA_FIELDS)})",
                "candidate_evidence": _candidates(usable, q_terms) if usable and usable[0][0] >= MIN_SCORE else [],
                "answer_text": "The sources have no metadata recording who approved or authored a document, or when, "
                               "so this is not answered. Policy text about approval roles is not a record of a "
                               "historical approver."}
    if not usable or usable[0][0] < MIN_SCORE:
        return {**base, "outcome": "abstained", "reason": "insufficient_evidence",
                "answer_text": "The policy corpus does not contain enough evidence to answer this. "
                               "No answer is given rather than a guess."}
    top_score, top = usable[0]
    coverage = len(q_terms & set(top.terms)) / len(q_terms)
    if coverage < MIN_COVERAGE:
        return {**base, "outcome": "abstained", "reason": f"low_term_coverage ({coverage:.0%} of question terms in "
                f"the best chunk)", "candidate_evidence": _candidates(usable, q_terms),
                "answer_text": "The closest source only partly matches the question, so no answer is given."}
    if top.topic:
        rivals = [c for c in corpus.chunks if c.topic == top.topic and c.position != top.position
                  and c.doc_id != top.doc_id and not c.injection_suspected]
        if rivals:
            sides = [top] + rivals[:2]
            retrieved = {c.chunk_id for _, c in usable}
            cites = [citation(c, _best_sentences(c, q_terms, 1)[0], i + 1) for i, c in enumerate(sides)]
            text = ("Sources disagree on this point, so no single answer is given. "
                    + " ".join(f"[{ct['n']}] {ct['title']} v{ct['version']} says: \"{ct['quote']}\"" for ct in cites)
                    + " A person should decide which source governs.")
            found = "all retrieved" if all(c.chunk_id in retrieved for c in rivals[:2]) else \
                "found via the topic tag across the corpus; not all were retrieved"
            return {**base, "outcome": "conflict", "reason": f"topic '{top.topic}' has positions "
                    + ", ".join(sorted({c.position for c in sides})) + f" ({found})", "answer_text": text,
                    "citations": cites}
    quotes = _best_sentences(top, q_terms)
    support = len(q_terms & set(terms(" ".join(quotes)))) / len(q_terms)
    if support < MIN_QUOTE_SUPPORT:
        return {**base, "outcome": "abstained",
                "reason": f"unsupported_by_quoted_text (best chunk {top.chunk_id} matched on {coverage:.0%} of terms, "
                          f"but its sentences contain only {support:.0%})",
                "candidate_evidence": _candidates(usable, q_terms),
                "answer_text": "A source matched some keywords, but none of its sentences addresses the question, so "
                               "no answer is given. The closest evidence is listed for a person to read."}
    cites = [citation(top, q, i + 1) for i, q in enumerate(quotes)]
    text = " ".join(f"\"{q}\" [{i + 1}]" for i, q in enumerate(quotes))
    caveat = {"fictional-policy": "Source is a fictional demo policy.",
              "fictional-brand": "Source is fictional brand guidance.",
              "unverified-summary": "Source is an unverified paraphrase, not current official text or legal advice.",
              "unverified-vendor-note": "Source is an unreviewed, untrusted vendor note."}.get(top.kind, "")
    return {**base, "outcome": "unverified_excerpts", "label": UNVERIFIED_LABEL, "reason": f"best match {top.chunk_id} (score {top_score:.2f}, "
            f"coverage {coverage:.0%}, quoted-text support {support:.0%})", "answer_text": f"{UNVERIFIED_LABEL}. {text} {caveat}".strip(),
            "citations": cites}


def resolve_citation(chunk_id: str) -> dict | None:
    c = get_corpus().by_id.get(chunk_id)
    if c is None:
        return None
    return {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "title": c.title, "version": c.version, "kind": c.kind,
            "trust": c.trust, "note": c.doc_note, "section": c.section, "heading": c.heading, "text": c.text,
            "sha256": c.sha256, "injection_suspected": c.injection_suspected}
