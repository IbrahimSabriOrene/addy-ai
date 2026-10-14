"""Observability, copied from the orchestrator's Documenter pattern: one
``BaseCallbackHandler`` registered at invoke time, watch-list = the 8 node
names + ladder events, fan-out to sinks. Per-event ``cost_cents`` makes
spend-per-job queryable from day one (PLAN.md "Observability")."""
