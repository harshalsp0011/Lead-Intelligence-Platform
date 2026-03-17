# Agentic Transformation Plan

## 1. Vision: What We Want To Build

Build an agentic lead-generation platform where the system decides what to do next at runtime instead of following only fixed, manual orchestration steps.

Target outcome:
- Airflow triggers runs on schedule.
- LangGraph controls in-run decisions.
- Agents select tools, evaluate outcomes, retry with new strategies, and stop using policy guardrails.
- Every run is observable, auditable, and improvable.

## 2. What "Agentic" Means In This Project

Agentic behavior we want:
- Dynamic planning: choose next action based on current state.
- Tool use: select among DB sources, Tavily, scraper, enrichment, writer, outreach.
- Critique and correction: evaluate output quality, then retry or branch.
- Memory: use prior run outcomes to improve future decisions.
- Bounded autonomy: policy limits for cost, retries, and approvals.

Not agentic behavior:
- Static step chains only.
- Hardcoded source order without runtime adaptation.
- No runtime quality evaluator.

## 3. Core Technology Stack

Primary runtime stack:
- LangGraph: orchestration brain (state machine, branching, loops, retries).
- LangChain: model + prompt + tool abstraction and structured outputs.
- FastAPI: trigger and status API.
- PostgreSQL: business data + agent memory + run logs.
- Airflow: scheduler and external trigger only.
- Tavily + scraping stack: discovery and collection tools.

Optional later:
- A2A protocol for cross-service agent communication.

## 4. A2A Protocol Decision

Phase 1-2 decision:
- Do not use A2A yet.

Why:
- Agents are in one codebase and one deployment boundary.
- LangGraph shared state is simpler and faster to implement.
- A2A adds distributed system overhead (transport, auth, routing, schema contracts).

When to adopt A2A:
- Teams own separate agent services independently.
- Agents need independent scaling or cross-platform federation.
- Multi-tenant agent interoperability is needed.

## 5. Agentic System Components

Required components:
- Planner: creates and updates run strategy.
- Executor nodes: Scout, Analyst, Writer, Outreach, Tracker actions.
- Critic/Evaluator: checks quality and confidence after each major step.
- Policy engine: budget, retry, compliance, approval rules.
- Memory manager: short-term and long-term learning.
- Observability layer: traces, metrics, cost, errors, decisions.

## 6. Memory Model

### 6.1 Short-term Memory (Run State)

Stored in LangGraph state during one run:
- target industry/location/count
- sources attempted and outcomes
- lead quality metrics
- errors and retries
- selected next action and rationale

### 6.2 Long-term Memory (Persistent)

Stored in PostgreSQL tables:
- source performance by industry/location
- successful and failed patterns
- prompt versions and quality scores
- run summaries and decision traces
- outreach outcome feedback

### 6.3 Retrieval Policy

At run start:
- Load prior source performance for target context.

During run:
- Update memory after each major node.

At run end:
- Persist summary, costs, and learning signals.

## 7. End-to-End Flow (Target)

1. Airflow triggers a run (schedule or manual).
2. FastAPI creates run context and starts LangGraph.
3. Planner node proposes strategy.
4. Scout strategy chooses source path:
- DB sources first
- Tavily fallback
- adaptive retries based on quality
5. Scrape/extract node collects leads.
6. Critic evaluates lead quality and coverage.
7. Branch:
- if quality is enough -> Analyst
- if quality is low -> replan and try alternate source strategy
8. Analyst scores and estimates value.
9. Enrichment fills contacts/signals.
10. Writer drafts messages.
11. Writer critic loop approves or rewrites.
12. Outreach sends only policy-compliant approved drafts.
13. Tracker captures replies/events.
14. Memory update writes learned outcomes.
15. Run completes with full trace and metrics.

## 8. Startup Flow (How It Starts)

Control-plane startup:
1. Docker services start.
2. API validates DB connectivity.
3. Airflow schedules DAG triggers.

Run startup:
1. Trigger request hits FastAPI.
2. API creates run record and initial state.
3. LangGraph run starts with policy constraints.
4. Planner selects initial tool path.

## 9. Observability Plan

### 9.1 Metrics

Track per run and per node:
- node latency
- success/failure counts
- retry counts
- lead yield by source
- enrichment success rate
- draft approval rate
- outreach and reply conversion
- token/tool/API cost

### 9.2 Logs and Traces

Capture:
- decision rationale at each branch
- input/output summaries per node
- error class and fallback decision
- policy gate outcomes

### 9.3 Dashboards and Alerts

Dashboards:
- run timeline and node outcomes
- source quality heatmap by industry/location
- cost per qualified lead

Alerts:
- repeated run failures
- quality below threshold
- abnormal cost spikes
- blocked approval queue

## 10. Phases We Will Work On

### Phase 0: Baseline and Guardrails

Goals:
- Define run state schema.
- Define policy limits (max retries, cost caps, approval gates).
- Add run and decision audit table(s).

Deliverables:
- documented state contract
- policy config
- baseline observability fields

### Phase 1: Agentic Scout

Goals:
- Convert Scout into multi-node graph (planner, execute, critic, replan).
- Use DB source memory + Tavily fallback adaptively.

Deliverables:
- dynamic source strategy
- quality-based retry loop
- source performance writeback

### Phase 2: Agentic Writer

Goals:
- Add writer planner/critic/rewrite loop.
- Use structured quality rubric for email outputs.

Deliverables:
- confidence-scored drafts
- rewrite loop with max attempts

### Phase 3: Cross-Stage Replanning

Goals:
- Add run-level replanning across Scout/Analyst/Writer.
- Introduce branch-on-failure pathways.

Deliverables:
- master graph with conditional edges
- failure recovery policies

### Phase 4: Learning and Optimization

Goals:
- Use long-term memory to improve source/prompt selection.
- Add outcome-based strategy tuning.

Deliverables:
- memory-driven strategy ranking
- prompt/source win-rate analytics

### Phase 5: Optional Distributed Agents (A2A)

Goals:
- adopt A2A only if separate deployable agent services are required.

Deliverables:
- inter-agent contracts
- service auth/routing/monitoring plan

## 11. What We Will Learn

Technical learning:
- how to design bounded autonomous workflows
- how to combine deterministic tools with LLM decisions
- how to evaluate and improve agent quality over time
- how to observe and debug agent behavior

Business learning:
- which sources produce highest-quality leads by context
- which outreach patterns convert best
- true cost per qualified lead and per meeting

## 12. What Becomes Unnecessary In Agentic World

Reduced/removed over time:
- hardcoded source ordering logic in multiple places
- fixed static step chaining for every run
- manual source list maintenance as primary mechanism
- brittle if/else orchestration spread across modules

Still necessary:
- policy controls and approval gates
- deterministic data validation
- compliance and audit logging

## 13. Success Criteria

System-level:
- higher qualified lead yield per run
- lower manual intervention per run
- stable run completion under failures
- explainable and auditable decisions

Ops-level:
- full run trace visibility
- measurable cost and quality metrics
- clear rollback and safe-mode behavior

## 14. Final Operating Model (End State)

End-state architecture:
- Airflow schedules and triggers.
- FastAPI hosts control-plane API.
- LangGraph runs the agentic workflow.
- LangChain standardizes LLM/tool interactions.
- PostgreSQL stores business data and agent memory.
- Observability stack shows decision traces, costs, and quality.

In short:
- Airflow says when to run.
- Agentic graph decides how to run.
- Tools execute real work.
- Memory improves each next run.
