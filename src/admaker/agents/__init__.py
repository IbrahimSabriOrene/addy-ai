"""LLM agent plumbing, copied from the AI Orchestrator (PLAN.md decision #8:
patterns are copied in, not imported). MobileAdMaker has only three LLM
touch-points — intake visibility check, style planner, content QA — so the
same AgentSpec factory carries them."""
