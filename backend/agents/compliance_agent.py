from backend.agents.base_agent import AgentSpec
from backend.contracts import ComplianceOutput
from backend.grounding import get_corpus
from backend.policy import COMPLIANCE_RULES, PRICE_RULE_CHUNK
from backend.prompts.templates import COMPLIANCE_SYSTEM


def _retrieved_sources(context: dict) -> dict:
    """Top policy chunks for each creative, plus the chunks the rule engine cites. Deterministic."""
    corpus = get_corpus()
    ids: list[str] = [chunk for _, _, chunk in COMPLIANCE_RULES.values()] + [PRICE_RULE_CHUNK]
    for cr in context.get("creative", {}).get("creatives", []):
        ids += [c.chunk_id for _, c in corpus.search(f"{cr['headline']} {cr['body']}", k=3)]
    seen, sources = set(), []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            c = corpus.by_id[cid]
            sources.append({"chunk_id": cid, "title": c.title, "version": c.version, "kind": c.kind,
                            "trust": c.trust, "injection_suspected": c.injection_suspected, "text": c.text})
    return {"retrieved_sources": sources}


def _citations_resolve(out, context: dict) -> None:
    corpus = get_corpus()
    creative_ids = {c["creative_id"] for c in context.get("creative", {}).get("creatives", [])}
    allowed = {s["chunk_id"] for s in context.get("retrieved_sources", []) if not s["injection_suspected"]}
    for f in out.findings:
        if f.citation_chunk_id not in corpus.by_id:
            raise ValueError("citation does not resolve to a corpus chunk")
        if f.citation_chunk_id not in allowed:
            raise ValueError("citation was not among the retrieved, non-flagged sources")
        if f.creative_id not in creative_ids:
            raise ValueError("finding refers to an unknown creative_id")


SPEC = AgentSpec(name="compliance", system_prompt=COMPLIANCE_SYSTEM, contract=ComplianceOutput, reads=("creative",),
                 extra_context=_retrieved_sources, semantic_check=_citations_resolve,
                 description="Policy review with citations that must resolve to corpus chunks")
