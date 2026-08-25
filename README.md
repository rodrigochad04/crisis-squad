# GCB Autonomous Crisis Squad

> **AI-native incident response** — a LangGraph pipeline whose Human-in-the-Loop gate is enforced by the graph topology, not by a prompt.

<!-- After forking, replace YOUR-USER below (two places) so the badge tracks your CI. -->
[![CI](https://github.com/rodrigochad04/crisis-squad/actions/workflows/ci.yml/badge.svg)](https://github.com/rodrigochad04/crisis-squad/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-green.svg)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Try it in three commands

Nothing external is required. Instana, Jira and Teams are mocked with real data
captured from a Robot-Shop-EKS proof of concept. An LLM is optional.

```bash
git clone <this-repo> && cd crisis-squad
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cp .env.demo .env
```

Then either open the dashboard:

```bash
uvicorn src.api.server:app --port 8000     # then open http://localhost:8000
```

or stay in the terminal:

```bash
python demo/run_demo.py                    # streams the graph, prompts at the gate
```

A full run takes a few seconds. **No API key is needed** — without one, the
playbook node uses a deterministic fallback and says so in the output. To
generate a real playbook, add a free [Groq](https://console.groq.com) key to
`.env` as `GROQ_API_KEY=...`.

---

## What actually happens

One compiled LangGraph executes every run. The REST API, the MCP server and the
terminal demo are all thin clients over the same graph object — there is no
second implementation of the pipeline anywhere in this repository.

```
START ─► instana ─► jira ─► rag ─► playbook ─► teams_war_room ─► hitl
                                                                   │
                                              interrupt_after=["hitl"]
                                                                   │
                                                        record_decision ─► END
```

| Node | What it does | Uses an LLM |
|---|---|---|
| `instana` | Error rate, p99 latency, blast radius, failure-pattern classification | no |
| `jira` | Searches historical precedents, opens the formal ticket | no |
| `rag` | Semantic search over local runbooks and postmortems (FAISS) | no |
| `playbook` | Generates a six-section Markdown remediation playbook | **yes** |
| `teams_war_room` | Opens the channel, posts the playbook | no |
| `hitl` | Registers the approval request — **the graph then stops** | no |
| `record_decision` | Writes the audit entry. Refuses to run without a decision | no |

### Why only one node uses an LLM

An earlier version wrapped every node in a ReAct agent. A ReAct loop that always
calls the same two tools in the same order buys nothing: it adds latency, token
cost and non-determinism to a step whose control flow was never in question.
Orchestration is now plain Python, and the LLM is used at the one point where
free text is genuinely the deliverable. This is the difference the role
description gets at — sometimes the right answer is an agent, and sometimes it
is a repeatable process. Here it is both, in different places.

A useful side effect: the diagnosis text is assembled deterministically, so every
metric is printed next to its seven-day baseline. `8ms` is always
`8ms vs 142ms baseline`. A model cannot drift away from numbers it never wrote.

---

## The governance gate

This is the part worth reviewing closely. The claim is that no production action
can happen without a recorded human decision, and it is defended in four places:

1. **Topology.** `interrupt_after=["hitl"]` means the compiled graph halts after
   registering the approval request. `record_decision` and everything downstream
   are unreachable until the checkpoint is explicitly updated and resumed.
2. **Node precondition.** `record_decision_node` raises if `approval_status` is
   not `APPROVED` or `REJECTED`. Remove the interrupt and this still holds.
3. **API state machine.** `POST /incidents/{run_id}/approve` returns `409` if the
   run has not reached the gate, and `409` if it was already decided. The first
   decision is final; the audit trail cannot be overwritten.
4. **Authentication.** That endpoint is bearer-guarded whenever
   `API_AUTH_ENABLED=true`. If auth is on and `API_SECRET_KEY` is still a
   placeholder, the server returns `500` rather than quietly allowing the call.

All four are asserted in `evaluation/test_governance.py`, including the
adversarial cases — approving before the gate, approving twice, and re-invoking
the graph to try to walk past the interrupt.

```bash
pytest evaluation/test_governance.py -v      # 16 tests, no LLM, no network
```

> **In demo mode auth is off** (`.env.demo` sets `API_AUTH_ENABLED=false`) so the
> dashboard works with zero setup. That is a deliberate, visible choice in a
> config file — not an unused dependency. For anything shared, use `.env.example`.

---

## Interfaces

| Surface | How to reach it |
|---|---|
| Live dashboard | `http://localhost:8000` |
| Metrics dashboard | `http://localhost:8000/metrics` |
| Swagger UI | `http://localhost:8000/docs` |
| Terminal | `python demo/run_demo.py` |
| Claude Code / Cursor | MCP server, auto-registered via `.mcp.json` |
| Claude Code slash commands | `.claude/commands/` |

### MCP server

```bash
python -m src.mcp_server                                # stdio
python -m src.mcp_server --transport sse --port 8001    # HTTP/SSE
```

Tools: `trigger_incident`, `get_dora_metrics`, `approve_incident`,
`list_incidents`, `generate_spec`. When the API has auth enabled, set
`GCB_API_TOKEN` in the `.mcp.json` env block to match `API_SECRET_KEY`.

### Slash commands

`/trigger-incident`, `/approve-incident`, `/show-metrics`, `/run-evaluation`,
`/generate-spec` — each with frontmatter declaring its `allowed-tools`.
`/approve-incident` deliberately shows you the pending action and the rollback
procedure before it will submit anything.

---

## Tech stack

| Layer | Technology |
|---|---|
| Orchestration | [LangGraph](https://langchain-ai.github.io/langgraph/) — `StateGraph`, `MemorySaver`, `interrupt_after` |
| LLM | Provider-agnostic. Groq, OpenAI, Anthropic, Ollama, or any OpenAI-compatible gateway via `LLM_MODEL` |
| Tools | LangChain `@tool` — typed, structured, individually testable |
| RAG | [FAISS](https://github.com/facebookresearch/faiss) + `BAAI/bge-small-en-v1.5`, with a keyword fallback |
| Observability | [OpenTelemetry](https://opentelemetry.io/) in-memory spans, exposed at `/metrics/traces` |
| Evaluation | [DeepEval](https://github.com/confident-ai/deepeval) with Groq as judge, plus deterministic pytest |
| API | [FastAPI](https://fastapi.tiangolo.com/) with SSE streaming |
| Config | [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — validated at import |
| CI | GitHub Actions — lint, types, secret scan, tests, Docker build with an end-to-end smoke test |

### Swapping the LLM

Change one line in `.env`:

```bash
LLM_MODEL=groq/qwen/qwen3.6-27b     # default
LLM_MODEL=openai/gpt-4o-mini        # + OPENAI_API_KEY
LLM_MODEL=anthropic/claude-sonnet-4-5   # + ANTHROPIC_API_KEY
LLM_MODEL=ollama/llama3.2           # fully local, no key
LLM_MODEL=my-model                  # + LLM_BASE_URL for a LiteLLM/vLLM gateway
```

---

## Evaluation

```bash
pytest evaluation/ -v                          # everything
pytest evaluation/test_governance.py -v        # gate guarantees only
```

41 tests pass without any credentials. Two more are LLM-graded and skip
themselves with a clear reason when no key is present — a skip is reported as
reduced coverage, never as a pass.

| File | Proves | Needs an LLM |
|---|---|---|
| `test_governance.py` | Gate cannot be bypassed, decisions immutable, auth wired | no |
| `test_agents.py::TestInstanaClient` | FAIL_FAST / SATURATION / LATENCY_DEGRADATION classification | no |
| `test_agents.py::TestJiraTools` | ISO timestamps, Atlassian ADF extraction | no |
| `test_agents.py::TestHitLGate` | Approval payload carries the required fields | no |
| `test_agents.py::TestPlaybook` | Six mandatory sections, kubectl commands, numeric criteria | partly |
| `test_agents.py::TestInstanaDiagnosis` | Faithfulness, no hallucinated fields | yes |
| `test_specification_agent.py` | Cost tracking and spec generation | no |

---

## Metrics, and what they are not

`/metrics/dora` reports MTTR, change failure rate, deployment frequency and the
five SPACE dimensions. **Most of these are proxies and the payload says so in its
own `description` fields.** Deployment frequency counts incidents handled per
session. MTTR measures how long the pipeline took, not how long a real outage
lasted. They demonstrate the instrumentation, not a production baseline. Wiring
the same collectors to real deployment and incident data is a configuration
change, not a rewrite — but it has not been done here.

`/metrics/cost` reports real token usage and estimated USD per run and per model,
attributed to the node that spent it.

---

## Demo mode versus production

| | `DEMO_MODE=true` | Production |
|---|---|---|
| Instana | Mocked with real PoC data | Real API |
| Jira | Mocked (KAN-142, KAN-118 precedents) | Real API |
| Teams | Mocked locally | Microsoft Graph |
| LLM | Real, or deterministic fallback | Any provider |
| RAG | Real FAISS, local | Same |
| HitL gate | **Real** | Same |
| Audit trail | In-memory | Persist to a database |
| Auth | Off by default | Bearer token required |

The demo runs a single scripted incident (`QKTtAivDTAaKvCGqvQOWpA`). The mock
layer returns the same fixture for any incident ID — the graph, the gate and the
audit trail are real, the observability data behind them is not.

### Known limitations

Stated plainly, because a reviewer will find them anyway:

- **The FAISS index needs a one-time model download.** The index is committed,
  but loading it still fetches `BAAI/bge-small-en-v1.5` (~130 MB) from
  HuggingFace on first use. The API warms the retriever at startup so an incident
  is never blocked on that download. If the model is still downloading — or
  HuggingFace is unreachable — retrieval degrades to keyword search after a
  20-second timeout and the `rag` node reports `backend: keyword-fallback`
  instead of pretending it did a vector search. The next run tries FAISS again.
- **State is in-memory.** `MemorySaver` and the incident index do not survive a
  restart. Swapping in the Postgres checkpointer is the obvious next step.
- **`/spec/generate` has no offline fallback** — it returns `503` without an LLM.

---

## Project structure

```
crisis-squad/
├── src/
│   ├── config.py                  # pydantic-settings, validated at import
│   ├── graph/crisis_graph.py      # THE pipeline — 7 nodes, interrupt_after HitL
│   ├── tools/                     # @tool wrappers: instana, jira, teams, hitl
│   ├── knowledge_base/retriever.py# FAISS index builder + MMR retriever
│   ├── agents/specification_agent.py
│   ├── evaluation/cost_tracker.py # token + USD attribution per node
│   ├── metrics/dora.py            # DORA + SPACE engine
│   ├── observability/tracing.py   # OpenTelemetry spans
│   ├── hooks/pre_commit_hook.py   # ruff + secret scan + optional AI review
│   ├── demo/                      # fixtures and mock implementations
│   ├── mcp_server.py              # 5 MCP tools, stdio + SSE
│   └── api/server.py              # FastAPI, SSE, auth, gate state machine
├── evaluation/
│   ├── test_governance.py         # gate guarantees (16 tests)
│   ├── test_agents.py             # diagnosis, playbook, tools
│   └── test_specification_agent.py
├── docs/ARCHITECTURE.md
├── docs/runbooks/                 # markdown corpus indexed into FAISS
├── .claude/commands/              # slash commands with frontmatter
├── .mcp.json                      # MCP registration
└── .github/workflows/ci.yml
```

---

## Docker

```bash
docker compose up --build     # API + Langfuse + Postgres
```

The image installs from `pyproject.toml` only, runs as a non-root user, and has
a `.dockerignore` that keeps `.env` and `.venv` out. CI builds it and then runs
a real incident through it to the gate, so a broken image fails the build rather
than the first person to pull it.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Install the pre-commit hook first:

```bash
python src/hooks/pre_commit_hook.py --install
```

It runs ruff, mypy on changed files, and a credential scan. CI runs the same
scan across all tracked files (`--scan-tracked`), because git-ignoring a `.env`
protects the repository but not an archive built from the working tree.

## License

MIT — see [LICENSE](LICENSE).
