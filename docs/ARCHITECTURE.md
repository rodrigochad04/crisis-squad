# Architecture

This document explains the internal architecture of the GCB Autonomous Crisis
Squad — an AI-native incident response system built on LangGraph.

## System overview

```
Browser / API client
       │
       │  POST /incidents          GET /incidents/{id}/stream
       ▼                                      ▼
┌──────────────────────────────────────────────────────┐
│                  FastAPI server                       │
│  src/api/server.py                                   │
│                                                      │
│  • Streams the compiled graph; never reimplements it         │
│  • Relays each node's ui_events over SSE          │
│  • Bearer-guards /incidents and /approve; enforces gate state           │
│  • Records DORA + SPACE metrics per run              │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│              LangGraph StateGraph                     │
│  src/graph/crisis_graph.py                           │
│                                                      │
│  IncidentState (TypedDict)                           │
│  ┌──────────────────────────────────────────────┐    │
│  │  instana → jira → rag → playbook → teams     │    │
│  │                          ↓                   │    │
│  │                         hitl                 │    │
│  │                          ↓                   │    │
│  │                 [interrupt_after]             │    │
│  │            ── graph halts here ──             │    │
│  │                          ↓                   │    │
│  │      update_state(approval_status) + resume   │    │
│  │                          ↓                   │    │
│  │                  record_decision → END        │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  Checkpointer: MemorySaver (in-memory, swappable)    │
└─────────┬────────────────────────────────────────────┘
          │
          │  @tool calls
          ▼
┌──────────────────────────────────────────────────────┐
│                    Tools layer                        │
│  src/tools/                                          │
│                                                      │
│  instana_tools.py   → get_incident_details           │
│                       get_blast_radius               │
│  jira_tools.py      → search_related_issues          │
│                       create_incident_ticket         │
│  teams_tools.py     → create_war_room                │
│                       post_update                    │
│  hitl_tools.py      → request_human_approval         │
│                       record_human_decision          │
│                                                      │
│  DEMO_MODE=true → all tools return mock data         │
│  (src/demo/mocks.py + src/demo/mock_data.py)         │
└─────────┬────────────────────────────────────────────┘
          │
          ├──── FAISS retriever ────────────────────────
          │     src/knowledge_base/retriever.py         │
          │     BAAI/bge-small-en-v1.5 (local)         │
          │     docs/runbooks/*.md → data/faiss_index/  │
          │                                             │
          ├──── LLM (ChatGroq / any provider) ──────────
          │     src/config.py → LLM_MODEL env var       │
          │     Groq Qwen 27B by default                │
          │                                             │
          ├──── OpenTelemetry spans ────────────────────
          │     src/observability/tracing.py            │
          │     In-memory exporter → /metrics/traces    │
          │                                             │
          ├──── DORA + SPACE metrics ───────────────────
          │     src/metrics/dora.py                     │
          │     MetricsStore singleton → /metrics/dora  │
          │                                             │
          └──── LLM cost tracker ───────────────────────
                src/evaluation/cost_tracker.py
                CostCallbackHandler → per-run USD cost
```

## Key design decisions

### HitL is structural

`interrupt_after=["hitl"]` in the LangGraph topology means the graph
itself enforces the pause — not an instruction to the LLM. An agent
following instructions can be confused or overridden; a graph interrupt
cannot.

### DEMO_MODE guards

Every external call is wrapped with a `DEMO_MODE` guard:

```python
if settings.demo_mode:
    return MOCK_DATA[incident_id]
return real_api_call(incident_id)
```

This makes the system fully runnable without any external credentials
while keeping production-ready code paths intact.

### Provider-agnostic LLM

`src/config.py` exposes `LLM_MODEL` as a string. `crisis_graph.py`
selects the provider based on the prefix:

| `LLM_MODEL` prefix | Provider |
|---|---|
| `groq/...` | ChatGroq |
| `openai/...` | ChatOpenAI |
| `anthropic/...` | ChatAnthropic |
| `ollama/...` | ChatOllama (local) |

No code changes are required to switch providers.

### Grounded diagnosis

The Instana agent is explicitly forbidden from mentioning fields not
present in the tool output (JVM heap, deployment versions, commit hashes).
Every metric is shown alongside its 7-day baseline so numbers are always
contextualised.

### Evaluation harness

`evaluation/test_agents.py` uses DeepEval with Groq as the LLM judge.
This means the evaluation suite is fully runnable without an OpenAI key
and costs a few cents per full run on Groq's free tier.

## Data flow for a single incident

```
1. POST /incidents {"incident_id": "QKTtAivDTAaKvCGqvQOWpA"}
   └─ Creates IncidentState, starts graph in background thread
   └─ Opens SSE queue, returns run_id immediately (202)

2. instana_node runs
   └─ calls get_incident_details + get_blast_radius tools
   └─ LLM synthesises diagnosis with pattern classification
   └─ State: instana_diagnosis = "FAIL_FAST — 100% error rate…"
   └─ SSE event: {phase: "instana", status: "complete"}

3. jira_node runs
   └─ calls search_related_issues + create_incident_ticket
   └─ State: jira_precedents = "KAN-142 (28 min), KAN-118 (45 min)…"

4. rag_node runs
   └─ FAISS MMR search over runbooks
   └─ State: kb_runbook = "## MCP Gateway FAIL_FAST Runbook…"

5. playbook_node runs
   └─ LLM generates 6-section Markdown playbook
   └─ State: playbook = "## Executive Summary\n…"

6. teams_node runs
   └─ create_war_room + post_update
   └─ State: war_room_channel_id = "demo-channel-id-…"

7. GRAPH PAUSES — interrupt_after=["hitl"]
   └─ SSE event: {phase: "awaiting_approval"}
   └─ Browser shows Approve / Reject buttons

8. POST /incidents/{run_id}/approve {"decision": "APPROVED", "decided_by": "sre-lead"}
   └─ Graph resumes from checkpoint
   └─ hitl_node executes (logs approval request)

9. record_decision_node runs
   └─ Tamper-evident audit record persisted
   └─ DORA metrics updated (MTTR, approval rate)
   └─ SSE event: {phase: "resolved", decision: "APPROVED"}
   └─ SSE stream closes
```

## Adding observability to production

The system ships with an in-memory OpenTelemetry exporter. To send spans
to a real collector, replace the exporter in `src/observability/tracing.py`:

```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
exporter = OTLPSpanExporter(endpoint="http://otel-collector:4317")
```

For Langfuse distributed tracing, set in `.env`:

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=gcb-crisis-squad
```

LangChain will send all LLM calls to Langfuse automatically.


## Why the interrupt is `after` and not `before`

An earlier revision used `interrupt_before=["hitl"]`. That halts the graph
*before* the gate node runs, which means the approval request is never
registered — there is no `approval_id` to show a human and nothing to audit.
`interrupt_after=["hitl"]` lets the gate node do its one job (record what is
being asked, with its evidence and risk level) and *then* stops. The distinction
matters: the pause must happen after the request exists and before anything can
act on it.

## Defence in depth at the gate

The topology is the first line, not the only one. Resuming an interrupted
LangGraph is a legitimate operation, so a caller holding the thread ID could
invoke the graph again and walk past the interrupt. `record_decision_node`
therefore validates its own precondition and raises if `approval_status` is
still `PENDING`. `evaluation/test_governance.py::test_reinvoking_without_a_decision_raises`
exercises exactly this path.

Above that, the API layer refuses to resume unless the checkpoint's `next` is
`record_decision`, rejects decisions for runs that have not reached the gate,
and rejects any second decision with `409`. Auth sits above all of it.

## Orchestration is deterministic

Only the `playbook` node calls an LLM. The data-gathering nodes call their tools
directly, in a fixed order. A ReAct loop around two tools whose call order is
already known adds latency, token cost and non-determinism without adding
capability — and it made the diagnosis text free to drift from the metrics the
tools returned. The diagnosis is now assembled by `_fmt_diagnosis`, which prints
every metric alongside its seven-day baseline by construction.

## Degradation paths

The system is designed to degrade visibly rather than hang or lie:

| Dependency missing | Behaviour | Surfaced as |
|---|---|---|
| No LLM key | Deterministic fallback playbook | `source: static-fallback` |
| HuggingFace unreachable | Keyword retrieval after a 20s timeout, remembered | `backend: keyword-fallback` |
| LLM call fails mid-run | Fallback playbook, run continues | `source: static-fallback (<error>)` |
| `msal` not installed | Teams mocks still work (lazy import) | — |

Each is reported in the node's `ui_events`, so the dashboard shows which path
was taken. A demo that silently substitutes a weaker component is worse than one
that says what it did.
