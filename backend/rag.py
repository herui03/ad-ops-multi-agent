"""
RAG module — lightweight TF-IDF search.
For small document sets (<100 chunks) this is fast, reliable,
and needs no external embedding API or heavy libraries.
"""

import os
import math
import re
from collections import Counter
from langchain_text_splitters import RecursiveCharacterTextSplitter

DOCS_PATH = os.path.join(os.path.dirname(__file__), "..", "rag_documents")

_chunks: list[str] = []
_chunk_tfs: list[dict[str, float]] = []
_idf: dict[str, float] = {}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _compute_tf(words: list[str]) -> dict[str, float]:
    counter = Counter(words)
    total = len(words)
    return {w: c / total for w, c in counter.items()} if total else {}


def init_rag():
    global _chunks, _chunk_tfs, _idf

    # Load documents
    texts: list[str] = []
    for root, _dirs, files in os.walk(DOCS_PATH):
        for fname in sorted(files):
            if fname.endswith(".txt"):
                with open(os.path.join(root, fname), "r", encoding="utf-8") as f:
                    texts.append(f.read())
    print(f"[RAG] Loaded {len(texts)} documents")

    # Split
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    _chunks = []
    for text in texts:
        _chunks.extend(splitter.split_text(text))
    print(f"[RAG] Split into {len(_chunks)} chunks")

    # Pre-compute TF per chunk & document frequency
    _chunk_tfs = []
    doc_freq: Counter = Counter()
    for chunk in _chunks:
        words = _tokenize(chunk)
        tf = _compute_tf(words)
        _chunk_tfs.append(tf)
        for w in set(words):
            doc_freq[w] += 1

    # IDF (smoothed)
    n = len(_chunks)
    _idf = {w: math.log((n + 1) / (df + 1)) + 1 for w, df in doc_freq.items()}

    print(f"[RAG] Indexed {len(_chunks)} chunks with TF-IDF (no external deps)")


def search_documents(query: str, k: int = 3) -> str:
    if not _chunks:
        return ""

    query_words = _tokenize(query)
    query_tf = _compute_tf(query_words)

    scores: list[tuple[float, int]] = []
    for i, chunk_tf in enumerate(_chunk_tfs):
        score = 0.0
        for w, qtf in query_tf.items():
            if w in chunk_tf:
                idf = _idf.get(w, 1.0)
                score += qtf * idf * chunk_tf[w] * idf
        scores.append((score, i))

    scores.sort(reverse=True)
    top = [_chunks[i] for score, i in scores[:k] if score > 0]
    return "\n\n---\n\n".join(top) if top else ""