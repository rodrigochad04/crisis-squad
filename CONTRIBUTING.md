# Contributing to GCB Autonomous Crisis Squad

Thank you for considering a contribution. This project is used as a technical
demonstration of AI-native engineering practices. Contributions that improve
correctness, add evaluation coverage, or extend the agentic tooling are welcome.

## Development setup

```bash
git clone <this-repo>
cd crisis-squad
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.demo .env          # pre-configured, no credentials needed
```

Install the AI-assisted pre-commit hook (optional but recommended):

```bash
python src/hooks/pre_commit_hook.py --install
```

The hook runs ruff, secret scanning, and an optional Groq-powered AI review
before every commit. It never blocks commits when the LLM is unavailable.

## Running checks locally

```bash
# Fast unit tests — no LLM calls (~5s)
pytest evaluation/ -v          # 41 deterministic tests, ~7s

# All tests including LLM-graded evaluation (requires GROQ_API_KEY)
pytest evaluation/ -v

# Lint
ruff check src/ evaluation/

# Format check
ruff format --check src/ evaluation/

# Type check
mypy src/ --ignore-missing-imports
```

## Branching model

| Branch | Purpose |
|---|---|
| `main` | Always deployable. Protected. Merges via PR only. |
| `feature/*` | New features or agents |
| `fix/*` | Bug fixes |
| `eval/*` | Evaluation harness changes |

## Pull request checklist

- [ ] Tests added or updated for new behaviour
- [ ] `ruff check` and `ruff format --check` pass
- [ ] No secrets in staged files (the pre-commit hook checks this)
- [ ] `DEMO_MODE=true` still works end-to-end
- [ ] PR description explains *why* the change is needed, not just *what* changed

## Adding a new agent node

1. Add the node function in [`src/graph/crisis_graph.py`](src/graph/crisis_graph.py)
2. Register it in `build_graph()` with `graph.add_node` and `graph.add_edge`
3. Add a system prompt constant following the `_<NAME>_SYSTEM` naming convention
4. Add at least one unit test in `evaluation/test_agents.py`
5. Update the node table in [`README.md`](README.md)

## Adding a new tool

1. Create `src/tools/<name>_tools.py` using the `@tool` decorator
2. Add a mock implementation in `src/demo/mocks.py` (guards with `DEMO_MODE`)
3. Wire the mock in `src/demo/mocks.py::_patch_tools()`
4. Add the tool to the relevant agent node's tool list

## Evaluation standards

LLM-graded tests use DeepEval with Groq as the judge. New tests must:
- Be deterministic on the mocked data (no random seeds)
- Include at least one assertion that does not require an LLM call
- Be skipped gracefully when `GROQ_API_KEY` is unset

## Code style

- **Line length**: 100 characters (ruff enforced)
- **Imports**: isort-style, absolute paths (`from src.tools.x import y`)
- **Type hints**: required for all public functions; use `Any` sparingly
- **Docstrings**: module-level and class-level are required; method docstrings for public API only

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add LangFuse callback to cost tracker
fix: SSE stream closes before resolved event arrives
docs: update architecture diagram
eval: add faithfulness test for RAG node
refactor: extract _strip_think to shared utility
```

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).
