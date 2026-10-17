# ADR 0001: Modular monolith and bounded recommendation graph

- Status: Proposed
- Date: 2026-10-17

## Context

The product needs external tool calls, multi-step reasoning, evidence validation,
ranking, conversational refinement, and eventually persistence. It also needs to
reach a public beta quickly and remain understandable as a portfolio project.

## Decision

Begin with one React web application and one modular FastAPI service. Implement
recommendation orchestration as a typed LangGraph with explicit nodes, bounded
retries, structured tool contracts, and deterministic validation around model
calls. Keep providers and model vendors behind interfaces.

## Consequences

- Local development, deployment, traces, and tests remain comparatively simple.
- Stored provider fixtures can replay recommendation flows without live network
  calls or model spend.
- The graph introduces state and checkpoint design work, but makes control flow
  more inspectable than a free-running agent.
- Service extraction remains possible if a measured scaling or ownership need
  emerges; it is not part of the beta plan.

