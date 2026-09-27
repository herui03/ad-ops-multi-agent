from backend.agents import analytics_agent, ci_agent, compliance_agent, creative_agent, insight_agent, strategy_agent

REGISTRY = {m.SPEC.name: m.SPEC for m in (insight_agent, strategy_agent, creative_agent, analytics_agent,
                                          compliance_agent, ci_agent)}
